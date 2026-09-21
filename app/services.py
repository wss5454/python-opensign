import base64
import io
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from PIL import Image
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.database import AuditEvent, Document, Signer, SignerWidget, User, utcnow
from app.mail import (
    MailError,
    document_url_for,
    resolve_base_url,
    send_signature_request,
    sign_url_for,
)


def generate_token() -> str:
    return secrets.token_urlsafe(32)


# Default signature slot size (% of page). Layout packs left→right, bottom→up.
WIDGET_SLOT_W = 28.0
WIDGET_SLOT_H = 10.0
WIDGET_GAP_X = 6.0
WIDGET_GAP_Y = 4.0
WIDGET_MARGIN_X = 8.0
WIDGET_START_Y = 82.0  # near bottom of page
WIDGET_COLS = 2
WIDGET_MIN_Y = 8.0


def _rects_overlap(a: dict, b: dict, pad: float = 0.5) -> bool:
    """Axis-aligned overlap check using page + percentage boxes."""
    if int(a.get("page", 1)) != int(b.get("page", 1)):
        return False
    ax, ay, aw, ah = float(a["x"]), float(a["y"]), float(a["w"]), float(a["h"])
    bx, by, bw, bh = float(b["x"]), float(b["y"]), float(b["w"]), float(b["h"])
    return not (
        ax + aw + pad <= bx
        or bx + bw + pad <= ax
        or ay + ah + pad <= by
        or by + bh + pad <= ay
    )


def slot_position(slot_index: int, page: int = 1) -> dict:
    """Ordered non-overlapping slot for signer/widget index (2 columns, bottom-up)."""
    rows_per_page = max(
        1,
        int((WIDGET_START_Y - WIDGET_MIN_Y) / (WIDGET_SLOT_H + WIDGET_GAP_Y)) + 1,
    )
    slots_per_page = WIDGET_COLS * rows_per_page
    widget_page = page + (slot_index // slots_per_page)
    local = slot_index % slots_per_page
    col = local % WIDGET_COLS
    row = local // WIDGET_COLS
    x = WIDGET_MARGIN_X + col * (WIDGET_SLOT_W + WIDGET_GAP_X)
    y = WIDGET_START_Y - row * (WIDGET_SLOT_H + WIDGET_GAP_Y)
    return {
        "type": "signature",
        "page": widget_page,
        "x": round(x, 2),
        "y": round(y, 2),
        "w": WIDGET_SLOT_W,
        "h": WIDGET_SLOT_H,
    }


def _default_widgets_for_role(role: str, slot_index: int = 0) -> List[dict]:
    if role == "viewer":
        return []
    return [slot_position(slot_index)]


def assign_ordered_widgets(signers: List[dict]) -> List[dict]:
    """Ensure each actionable signer gets ordered, non-overlapping widget slots.

    - Signers are processed in order_index (then list order).
    - Empty widgets → auto-assign next free slot.
    - Provided widgets that collide with earlier ones are shifted to the next free slot,
      unless they carry a field_name (AcroForm-anchored; keep the original rect).
    """
    ordered = sorted(
        enumerate(signers),
        key=lambda pair: (pair[1].get("order_index", pair[0]), pair[0]),
    )
    placed: List[dict] = []
    next_slot = 0
    result = [dict(s) for s in signers]

    for original_index, signer in ordered:
        role = signer.get("role", "signer")
        widgets_in = list(signer.get("widgets") or [])

        if role == "viewer":
            result[original_index]["widgets"] = []
            continue

        if not widgets_in:
            widget = slot_position(next_slot)
            next_slot += 1
            placed.append(widget)
            result[original_index]["widgets"] = [widget]
            continue

        fixed = []
        for w in widgets_in:
            field_name = w.get("field_name") or None
            candidate = {
                "type": w.get("type", "signature"),
                "page": int(w.get("page", 1)),
                "x": float(w["x"]),
                "y": float(w["y"]),
                "w": float(w["w"]),
                "h": float(w["h"]),
            }
            if field_name:
                candidate["field_name"] = field_name
            else:
                safety = 0
                while any(_rects_overlap(candidate, p) for p in placed) and safety < 50:
                    candidate = {
                        **slot_position(next_slot, page=int(candidate["page"])),
                        "type": candidate["type"],
                    }
                    next_slot += 1
                    safety += 1
                placed.append(candidate)
                next_slot = max(next_slot, len(placed))
            fixed.append(candidate)
        result[original_index]["widgets"] = fixed

    return result


def get_or_create_user(db: Session, name: str, email: str) -> User:
    user = db.query(User).filter(User.email == email).first()
    if user:
        return user
    user = User(name=name, email=email)
    db.add(user)
    db.flush()
    return user


def add_audit(
    db: Session,
    document_id: int,
    event_type: str,
    message: str,
    signer_id: Optional[int] = None,
    ip_address: Optional[str] = None,
) -> AuditEvent:
    event = AuditEvent(
        document_id=document_id,
        signer_id=signer_id,
        event_type=event_type,
        message=message,
        ip_address=ip_address,
    )
    db.add(event)
    return event


def save_upload(filename: str, content: bytes) -> Path:
    safe_name = Path(filename).name
    unique = f"{uuid.uuid4().hex}_{safe_name}"
    dest = settings.uploads_dir / unique
    dest.write_bytes(content)
    return dest


def decode_signature_image(data_url: str) -> Path:
    """Decode a base64 PNG data URL and save it."""
    if "," in data_url:
        _, encoded = data_url.split(",", 1)
    else:
        encoded = data_url

    raw = base64.b64decode(encoded)
    path = settings.signatures_dir / f"{uuid.uuid4().hex}.png"
    Image.open(io.BytesIO(raw)).convert("RGBA").save(path, format="PNG")
    return path


def _normalize_widget_pct(value: float) -> float:
    """Accept WallaceSign percentages (0-100) or larger unit scales (e.g. 0-1000)."""
    if value > 100:
        return value / 10.0 if value <= 1000 else min(value / 10.0, 100.0)
    return value


def widget_pdf_rect(widget: SignerWidget, page_width: float, page_height: float) -> tuple:
    """Convert widget % coords (top-left origin) to PDF points (bottom-left origin)."""
    x = _normalize_widget_pct(widget.x)
    y = _normalize_widget_pct(widget.y)
    w = _normalize_widget_pct(widget.w)
    h = _normalize_widget_pct(widget.h)

    pdf_w = (w / 100.0) * page_width
    pdf_h = (h / 100.0) * page_height
    pdf_x = (x / 100.0) * page_width
    pdf_y = page_height - ((y / 100.0) * page_height) - pdf_h
    return pdf_x, pdf_y, pdf_w, pdf_h


def _ensure_form_appearances(writer: PdfWriter) -> None:
    """Ask viewers to regenerate AcroForm appearances so filled values print."""
    setter = getattr(writer, "set_need_appearances_writer", None)
    if callable(setter):
        try:
            setter(True)
        except Exception:
            pass


def apply_widgets_to_pdf(
    source_pdf: Path,
    widgets: Sequence[SignerWidget],
    signature_paths: Dict[int, Path],
    signer_name: str,
    output_path: Path,
) -> Path:
    """Stamp signature images onto the PDF without dropping filled form fields.

    Cloning via append() keeps the AcroForm catalog (name, address, etc.).
    add_page() copies page drawings only and was wiping those values.
    """
    del signer_name  # reserved for future visible signer labels

    reader = PdfReader(str(source_pdf))
    writer = PdfWriter()
    writer.append(reader)

    overlays: Dict[int, list] = {}
    for widget in widgets:
        sig_path = signature_paths.get(widget.id)
        if not sig_path or not Path(sig_path).exists():
            continue
        page_index = max(widget.page, 1) - 1
        if page_index >= len(writer.pages):
            page_index = len(writer.pages) - 1
        overlays.setdefault(page_index, []).append((widget, Path(sig_path)))

    for i, page in enumerate(writer.pages):
        if i not in overlays:
            continue
        page_width = float(page.mediabox.width)
        page_height = float(page.mediabox.height)
        packet = io.BytesIO()
        c = canvas.Canvas(packet, pagesize=(page_width, page_height))
        for widget, sig_path in overlays[i]:
            pdf_x, pdf_y, pdf_w, pdf_h = widget_pdf_rect(widget, page_width, page_height)
            c.drawImage(
                str(sig_path),
                pdf_x,
                pdf_y,
                width=pdf_w,
                height=pdf_h,
                mask="auto",
                preserveAspectRatio=True,
                anchor="c",
            )
        c.save()
        packet.seek(0)
        overlay_page = PdfReader(packet).pages[0]
        page.merge_page(overlay_page)

    _ensure_form_appearances(writer)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        writer.write(f)
    return output_path


def create_document(
    db: Session,
    title: str,
    description: str,
    sequential: bool,
    owner_name: str,
    owner_email: str,
    filename: str,
    file_content: bytes,
    signers: List[dict],
    dealership_name: Optional[str] = None,
) -> Document:
    owner = get_or_create_user(db, owner_name, owner_email)
    path = save_upload(filename, file_content)
    signers = assign_ordered_widgets(signers)

    doc = Document(
        title=title,
        description=description or "",
        filename=Path(filename).name,
        dealership_name=(dealership_name or "").strip() or None,
        original_path=str(path),
        status="draft",
        sequential=sequential,
        public_token=generate_token(),
        owner_id=owner.id,
    )
    db.add(doc)
    db.flush()

    for idx, s in enumerate(signers):
        role = s.get("role", "signer")
        signer = Signer(
            document_id=doc.id,
            name=s["name"],
            email=s["email"],
            role=role,
            order_index=s.get("order_index", idx),
            phase=int(s.get("phase", 0) or 0),
            field_name=s.get("field_name") or None,
            access_token=generate_token(),
            status="pending",
        )
        db.add(signer)
        db.flush()

        widgets = s.get("widgets") or []
        if not widgets and role in ("signer", "approver"):
            widgets = _default_widgets_for_role(role, slot_index=idx)

        for w in widgets:
            db.add(
                SignerWidget(
                    signer_id=signer.id,
                    type=w.get("type", "signature"),
                    page=int(w.get("page", 1)),
                    x=float(w["x"]),
                    y=float(w["y"]),
                    w=float(w["w"]),
                    h=float(w["h"]),
                    field_name=w.get("field_name") or None,
                )
            )

    add_audit(db, doc.id, "created", f"Document '{title}' created by {owner_email}")
    db.commit()
    db.refresh(doc)
    return doc


def _actionable_signers(document: Document) -> List[Signer]:
    return [s for s in document.signers if s.role in ("signer", "approver")]


def active_phase(document: Document) -> Optional[int]:
    """Lowest phase that still has outstanding signer/approver rows."""
    pending_phases = [
        s.phase
        for s in _actionable_signers(document)
        if s.status not in ("signed", "declined")
    ]
    if not pending_phases:
        return None
    return min(pending_phases)


def _signers_to_email(document: Document) -> List[Signer]:
    """Who should receive a signature email right now (current phase only)."""
    current = active_phase(document)
    if current is None:
        return []
    actionable = [
        s
        for s in _actionable_signers(document)
        if s.phase == current and s.status not in ("signed", "declined")
    ]
    if not actionable:
        return []
    if document.sequential:
        active = get_active_signer(document)
        return [active] if active else []
    return sorted(actionable, key=lambda s: s.order_index)


def email_signature_requests(
    db: Session,
    document: Document,
    signers: Sequence[Signer],
    *,
    base_url: Optional[str] = None,
) -> None:
    """Send signature-request emails. No-op when mail is disabled."""
    if not settings.mail_enabled or not signers:
        return

    base = resolve_base_url(base_url)
    doc_url = document_url_for(document.public_token, base)
    errors: List[str] = []

    for signer in signers:
        try:
            send_signature_request(
                signer_name=signer.name,
                signer_email=signer.email,
                document_title=document.title,
                sign_url=sign_url_for(signer.access_token, base),
                document_url=doc_url,
                dealership_name=getattr(document, "dealership_name", None),
            )
            add_audit(
                db,
                document.id,
                "email_sent",
                f"Signature request emailed to {signer.name} ({signer.email})",
                signer_id=signer.id,
            )
        except MailError as exc:
            errors.append(str(exc))
            add_audit(
                db,
                document.id,
                "email_failed",
                f"Failed to email {signer.name} ({signer.email}): {exc}",
                signer_id=signer.id,
            )

    db.commit()
    if errors:
        raise MailError("; ".join(errors))


def send_document(
    db: Session,
    document: Document,
    ip_address: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Document:
    if document.status not in ("draft", "voided"):
        raise ValueError("Document cannot be sent in its current status")
    if not document.signers:
        raise ValueError("Add at least one signer before sending")

    for signer in document.signers:
        if signer.role in ("signer", "approver") and not signer.widgets:
            raise ValueError(
                f"Signer '{signer.name}' has no signature widgets. "
                "Each signer needs at least one widget location."
            )

    document.status = "sent"
    document.updated_at = utcnow()
    add_audit(
        db,
        document.id,
        "sent",
        f"Document sent to {len(document.signers)} signer(s)",
        ip_address=ip_address,
    )
    db.commit()
    db.refresh(document)

    email_signature_requests(
        db,
        document,
        _signers_to_email(document),
        base_url=base_url,
    )
    db.refresh(document)
    return document


def create_and_send_document(
    db: Session,
    title: str,
    description: str,
    sequential: bool,
    owner_name: str,
    owner_email: str,
    filename: str,
    file_content: bytes,
    signers: List[dict],
    ip_address: Optional[str] = None,
    base_url: Optional[str] = None,
    dealership_name: Optional[str] = None,
) -> Document:
    """Create a document and immediately move it to sent status."""
    doc = create_document(
        db=db,
        title=title,
        description=description,
        sequential=sequential,
        owner_name=owner_name,
        owner_email=owner_email,
        filename=filename,
        file_content=file_content,
        signers=signers,
        dealership_name=dealership_name,
    )
    # Reload with signers/widgets for send validation
    doc = (
        db.query(Document)
        .options(
            joinedload(Document.signers).joinedload(Signer.widgets),
        )
        .filter(Document.id == doc.id)
        .first()
    )
    return send_document(db, doc, ip_address=ip_address, base_url=base_url)


def void_document(db: Session, document: Document, ip_address: Optional[str] = None) -> Document:
    if document.status == "completed":
        raise ValueError("Completed documents cannot be voided")
    document.status = "voided"
    document.updated_at = utcnow()
    add_audit(db, document.id, "voided", "Document voided", ip_address=ip_address)
    db.commit()
    db.refresh(document)
    return document


def _safe_unlink(path_str: Optional[str]) -> None:
    if not path_str:
        return
    path = Path(path_str)
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        pass


def delete_document(db: Session, document: Document) -> None:
    """Permanently delete a document, related DB rows, and stored files."""
    file_paths = [document.original_path, document.signed_path]
    for signer in document.signers:
        file_paths.append(signer.signature_path)
        for widget in signer.widgets:
            file_paths.append(widget.signature_path)

    db.delete(document)
    db.commit()

    for path_str in file_paths:
        _safe_unlink(path_str)


def get_active_signer(document: Document) -> Optional[Signer]:
    current = active_phase(document)
    pending = [
        s
        for s in document.signers
        if s.status not in ("signed", "declined")
        and s.role != "viewer"
        and (current is None or s.phase == current)
    ]
    if not pending:
        return None
    if not document.sequential:
        return None
    return sorted(pending, key=lambda s: s.order_index)[0]


def can_signer_act(document: Document, signer: Signer) -> bool:
    if document.status in ("voided", "completed", "draft"):
        return False
    if signer.role == "viewer":
        return False
    if signer.status in ("signed", "declined"):
        return False
    current = active_phase(document)
    if current is not None and signer.phase != current:
        return False
    if document.sequential:
        active = get_active_signer(document)
        return active is not None and active.id == signer.id
    return True


def decline_document(
    db: Session,
    document: Document,
    signer: Signer,
    ip_address: Optional[str] = None,
) -> Document:
    if document.status in ("voided", "completed", "draft"):
        raise ValueError("Document cannot be declined in its current status")
    if signer.status == "signed":
        raise ValueError("Already signed documents cannot be declined")
    if signer.role == "viewer":
        raise ValueError("Viewers cannot decline")

    signer.status = "declined"
    signer.ip_address = ip_address
    document.status = "voided"
    document.updated_at = utcnow()
    add_audit(
        db,
        document.id,
        "declined",
        f"{signer.name} ({signer.email}) declined to sign",
        signer_id=signer.id,
        ip_address=ip_address,
    )
    add_audit(
        db,
        document.id,
        "voided",
        "Document voided because a signer declined",
        ip_address=ip_address,
    )
    db.commit()
    db.refresh(document)
    return document


def sign_document(
    db: Session,
    document: Document,
    signer: Signer,
    signatures: List[dict],
    ip_address: Optional[str] = None,
    legacy_signature_data: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Document:
    if not can_signer_act(document, signer):
        raise ValueError("Signer is not allowed to sign this document yet")

    signature_widgets = [w for w in signer.widgets if w.type in ("signature", "initials", "stamp")]
    if not signature_widgets:
        raise ValueError("No signature widgets assigned to this signer")

    by_id = {item["widget_id"]: item["signature_data"] for item in signatures if "widget_id" in item}

    # Legacy: one pad applies to the first signature widget
    if legacy_signature_data and signature_widgets:
        by_id.setdefault(signature_widgets[0].id, legacy_signature_data)

    missing = [w.id for w in signature_widgets if w.id not in by_id]
    if missing:
        raise ValueError(f"Missing signatures for widget id(s): {missing}")

    signature_paths: Dict[int, Path] = {}
    for widget in signature_widgets:
        path = decode_signature_image(by_id[widget.id])
        widget.signature_path = str(path)
        signature_paths[widget.id] = path

    first_path = signature_paths[signature_widgets[0].id]
    signer.signature_path = str(first_path)
    signer.status = "signed"
    signer.signed_at = utcnow()
    signer.ip_address = ip_address

    source = Path(document.signed_path or document.original_path)
    out_name = f"doc_{document.id}_{signer.id}_{uuid.uuid4().hex[:8]}.pdf"
    out_path = settings.signed_dir / out_name
    apply_widgets_to_pdf(source, signature_widgets, signature_paths, signer.name, out_path)
    document.signed_path = str(out_path)

    add_audit(
        db,
        document.id,
        "signed",
        f"{signer.name} ({signer.email}) signed the document "
        f"({len(signature_widgets)} widget(s))",
        signer_id=signer.id,
        ip_address=ip_address,
    )

    actionable = _actionable_signers(document)
    all_signed = all(s.status == "signed" for s in actionable)
    next_phase = None if all_signed else active_phase(document)
    phase_advanced = next_phase is not None and next_phase != signer.phase

    if all_signed:
        document.status = "completed"
        document.completed_at = utcnow()
        add_audit(
            db,
            document.id,
            "completed",
            "All signers have completed the document",
            ip_address=ip_address,
        )
    else:
        document.status = "partially_signed"
        if phase_advanced:
            add_audit(
                db,
                document.id,
                "phase_advanced",
                f"Customer signatures complete; inviting phase {next_phase} signers",
                ip_address=ip_address,
            )

    document.updated_at = utcnow()
    db.commit()
    db.refresh(document)

    # Invite the next signer (sequential) or the next phase (company after customers).
    if not all_signed and (document.sequential or phase_advanced):
        try:
            email_signature_requests(
                db,
                document,
                _signers_to_email(document),
                base_url=base_url,
            )
        except MailError:
            # Signing already succeeded; email failure is audited separately.
            pass

    return document


def mark_viewed(
    db: Session,
    document: Document,
    signer: Signer,
    ip_address: Optional[str] = None,
) -> None:
    if signer.status == "pending":
        signer.status = "viewed"
        add_audit(
            db,
            document.id,
            "viewed",
            f"{signer.name} viewed the document",
            signer_id=signer.id,
            ip_address=ip_address,
        )
        db.commit()
