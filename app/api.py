import json
from typing import List, Optional

from pydantic import ValidationError
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, joinedload

from app import services
from app.config import settings
from app.database import Document, Signer, get_db
from app.mail import MailError
from app.schemas import (
    AuditEventOut,
    DocumentListItem,
    DocumentOut,
    HealthOut,
    SignerCreate,
    SignRequest,
    SignerOut,
    WidgetOut,
)
from app.ws import emit_document_finished

api_router = APIRouter(prefix="/api")


def _client_ip(request: Request) -> Optional[str]:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


def _base(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _widget_out(widget) -> WidgetOut:
    return WidgetOut(
        id=widget.id,
        type=widget.type,
        page=widget.page,
        x=widget.x,
        y=widget.y,
        w=widget.w,
        h=widget.h,
        field_name=getattr(widget, "field_name", None),
        has_signature=bool(widget.signature_path),
    )


def _signer_out(signer: Signer, request: Request) -> SignerOut:
    return SignerOut(
        id=signer.id,
        name=signer.name,
        email=signer.email,
        role=signer.role,
        order_index=signer.order_index,
        phase=getattr(signer, "phase", 0) or 0,
        field_name=getattr(signer, "field_name", None),
        status=signer.status,
        access_token=signer.access_token,
        sign_url=f"{_base(request)}/sign/{signer.access_token}",
        signed_at=signer.signed_at,
        widgets=[_widget_out(w) for w in signer.widgets],
    )


def _document_out(doc: Document, request: Request) -> DocumentOut:
    return DocumentOut(
        id=doc.id,
        title=doc.title,
        description=doc.description or "",
        filename=doc.filename,
        status=doc.status,
        sequential=doc.sequential,
        public_token=doc.public_token,
        document_url=f"{_base(request)}/d/{doc.public_token}",
        created_at=doc.created_at,
        updated_at=doc.updated_at,
        completed_at=doc.completed_at,
        signers=[_signer_out(s, request) for s in doc.signers],
    )


def _load_document(db: Session, document_id: int) -> Optional[Document]:
    return (
        db.query(Document)
        .options(
            joinedload(Document.signers).joinedload(Signer.widgets),
            joinedload(Document.audit_events),
        )
        .filter(Document.id == document_id)
        .first()
    )


def _load_signer_by_token(db: Session, token: str) -> Optional[Signer]:
    return (
        db.query(Signer)
        .options(
            joinedload(Signer.widgets),
            joinedload(Signer.document).joinedload(Document.signers).joinedload(Signer.widgets),
        )
        .filter(Signer.access_token == token)
        .first()
    )


@api_router.get("/health", response_model=HealthOut)
def health():
    return HealthOut(
        status="ok",
        app=settings.app_name,
        version=settings.app_version,
        database=settings.database_backend(),
    )


@api_router.get("/documents", response_model=List[DocumentListItem])
def list_documents(
    request: Request,
    db: Session = Depends(get_db),
):
    docs = (
        db.query(Document)
        .options(joinedload(Document.signers))
        .order_by(Document.created_at.desc())
        .all()
    )
    result = []
    for doc in docs:
        actionable = [s for s in doc.signers if s.role in ("signer", "approver")]
        result.append(
            DocumentListItem(
                id=doc.id,
                title=doc.title,
                filename=doc.filename,
                status=doc.status,
                public_token=doc.public_token,
                document_url=f"{_base(request)}/d/{doc.public_token}",
                created_at=doc.created_at,
                signer_count=len(actionable),
                signed_count=sum(1 for s in actionable if s.status == "signed"),
            )
        )
    return result


SIGNERS_JSON_EXAMPLE = json.dumps(
    [
        {
            "name": "Ada Lovelace",
            "email": "ada@example.com",
            "role": "signer",
            "order_index": 0,
            "phase": 0,
            "field_name": "sig1",
            "widgets": [
                {
                    "type": "signature",
                    "page": 1,
                    "x": 8.0,
                    "y": 82.0,
                    "w": 28.0,
                    "h": 10.0,
                    "field_name": "sig1",
                }
            ],
        },
        {
            "name": "Marina Owner",
            "email": "office@wallace1.com",
            "role": "signer",
            "order_index": 0,
            "phase": 1,
            "field_name": "companysig1",
            "widgets": [
                {
                    "type": "signature",
                    "page": 1,
                    "x": 42.0,
                    "y": 82.0,
                    "w": 28.0,
                    "h": 10.0,
                    "field_name": "companysig1",
                }
            ],
        },
    ]
)

SIGNERS_JSON_HELP = (
    "JSON array of signers. Each signer may include `widgets` "
    "(page + x/y/w/h as % of page, origin top-left) and optional `field_name`. "
    "`phase` is 0 for customers (sig1..) and 1 for company/marina (companysig1..); "
    "phase 1 is invited only after every phase 0 signer has signed. "
    "If `widgets` is omitted for a signer/approver, WallaceSign auto-assigns "
    "ordered non-overlapping slots (same as the UI). Example:\n\n"
    f"```json\n{SIGNERS_JSON_EXAMPLE}\n```"
)


async def _parse_document_upload(
    title: str,
    description: str,
    sequential: bool,
    signers_json: str,
    file: UploadFile,
) -> tuple[str, str, bool, list, str, bytes]:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    try:
        raw_signers = json.loads(signers_json)
        if not isinstance(raw_signers, list):
            raise ValueError("signers_json must be a JSON array")
        # Validate shape (including optional widgets) the same way as the UI payload
        signers = [SignerCreate.model_validate(item).model_dump() for item in raw_signers]
    except (json.JSONDecodeError, ValueError, ValidationError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid signers_json: {exc}") from exc

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")

    return title, description, sequential, signers, file.filename, content


@api_router.post(
    "/documents",
    response_model=DocumentOut,
    summary="Create document (draft)",
    description=(
        "Upload a PDF and create a document in **draft** status.\n\n"
        "Pass signers (and optional widget positions) in `signers_json` — "
        "same structure the UI sends. "
        "Call `POST /api/documents/{id}/send` afterwards, "
        "or use `POST /api/documents/create-and-send` to create and send in one step.\n\n"
        + SIGNERS_JSON_HELP
    ),
)
async def create_document(
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    sequential: bool = Form(False),
    signers_json: str = Form(
        ...,
        description=SIGNERS_JSON_HELP,
        examples=[SIGNERS_JSON_EXAMPLE],
    ),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    title, description, sequential, signers, filename, content = await _parse_document_upload(
        title, description, sequential, signers_json, file
    )

    try:
        doc = services.create_document(
            db=db,
            title=title,
            description=description,
            sequential=sequential,
            owner_name=settings.admin_name,
            owner_email=settings.admin_email,
            filename=filename,
            file_content=content,
            signers=signers,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    doc = _load_document(db, doc.id)
    return _document_out(doc, request)


@api_router.post(
    "/documents/create-and-send",
    response_model=DocumentOut,
    summary="Create document and send",
    description=(
        "Upload a PDF, create the document, and immediately set status to **sent** "
        "in a single request. Emails signing links when mail is enabled. "
        "Same multipart fields as create-document, including widgets "
        "inside `signers_json`. No auth cookie required.\n\n"
        + SIGNERS_JSON_HELP
    ),
)
async def create_and_send_document(
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    sequential: bool = Form(False),
    signers_json: str = Form(
        ...,
        description=SIGNERS_JSON_HELP,
        examples=[SIGNERS_JSON_EXAMPLE],
    ),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    title, description, sequential, signers, filename, content = await _parse_document_upload(
        title, description, sequential, signers_json, file
    )

    try:
        doc = services.create_and_send_document(
            db=db,
            title=title,
            description=description,
            sequential=sequential,
            owner_name=settings.admin_name,
            owner_email=settings.admin_email,
            filename=filename,
            file_content=content,
            signers=signers,
            ip_address=_client_ip(request),
            base_url=_base(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except MailError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Document created but email failed: {exc}",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    doc = _load_document(db, doc.id)
    return _document_out(doc, request)


@api_router.get("/documents/{document_id}", response_model=DocumentOut)
def get_document(
    document_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    doc = _load_document(db, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return _document_out(doc, request)


@api_router.get("/d/{public_token}", response_model=DocumentOut)
def get_document_by_token(public_token: str, request: Request, db: Session = Depends(get_db)):
    doc = (
        db.query(Document)
        .options(joinedload(Document.signers).joinedload(Signer.widgets))
        .filter(Document.public_token == public_token)
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return _document_out(doc, request)


@api_router.post(
    "/documents/{document_id}/send",
    response_model=DocumentOut,
    summary="Send existing document",
    description=(
        "Move a draft (or voided) document to **sent** status and email each "
        "signer their unique signing link (when mail is enabled)."
    ),
)
def send_document(
    document_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    doc = _load_document(db, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        doc = services.send_document(
            db,
            doc,
            ip_address=_client_ip(request),
            base_url=_base(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except MailError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Document marked sent but email failed: {exc}",
        ) from exc
    return _document_out(doc, request)


@api_router.post("/documents/{document_id}/void", response_model=DocumentOut)
def void_document(
    document_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    doc = _load_document(db, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        doc = services.void_document(db, doc, ip_address=_client_ip(request))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _document_out(doc, request)


@api_router.delete("/documents/{document_id}")
def delete_document(
    document_id: int,
    db: Session = Depends(get_db),
):
    doc = _load_document(db, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    services.delete_document(db, doc)
    return {"ok": True, "deleted_id": document_id}


@api_router.get("/documents/{document_id}/audit", response_model=List[AuditEventOut])
def document_audit(
    document_id: int,
    db: Session = Depends(get_db),
):
    doc = _load_document(db, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc.audit_events


@api_router.get("/documents/{document_id}/file")
def download_document(document_id: int, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    path = doc.signed_path or doc.original_path
    return FileResponse(path, media_type="application/pdf", filename=doc.filename)


@api_router.get("/d/{public_token}/file")
def download_document_by_token(public_token: str, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.public_token == public_token).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    path = doc.signed_path or doc.original_path
    return FileResponse(path, media_type="application/pdf", filename=doc.filename)


@api_router.get("/sign/{token}")
def get_signing_session(token: str, request: Request, db: Session = Depends(get_db)):
    signer = _load_signer_by_token(db, token)
    if not signer:
        raise HTTPException(status_code=404, detail="Invalid signing link")

    doc = signer.document
    services.mark_viewed(db, doc, signer, ip_address=_client_ip(request))
    db.refresh(signer)

    active = services.get_active_signer(doc) if doc.sequential else None
    return {
        "document": _document_out(doc, request),
        "signer": _signer_out(signer, request),
        "widgets": [_widget_out(w) for w in signer.widgets],
        "can_sign": services.can_signer_act(doc, signer),
        "pdf_url": f"/api/documents/{doc.id}/file",
        "active_signer": _signer_out(active, request) if active else None,
    }


@api_router.post("/sign/{token}", response_model=DocumentOut)
async def submit_signature(
    token: str,
    payload: SignRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    if not payload.consent:
        raise HTTPException(status_code=400, detail="Consent is required to sign")

    signer = _load_signer_by_token(db, token)
    if not signer:
        raise HTTPException(status_code=404, detail="Invalid signing link")

    signatures = [
        {"widget_id": item.widget_id, "signature_data": item.signature_data}
        for item in payload.signatures
    ]

    try:
        doc = services.sign_document(
            db,
            signer.document,
            signer,
            signatures,
            ip_address=_client_ip(request),
            legacy_signature_data=payload.signature_data,
            base_url=_base(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Signing failed: {exc}") from exc

    doc = _load_document(db, doc.id)
    if doc and doc.status == "completed":
        await emit_document_finished(doc)
    return _document_out(doc, request)


@api_router.post("/sign/{token}/decline", response_model=DocumentOut)
def decline_signature(token: str, request: Request, db: Session = Depends(get_db)):
    signer = _load_signer_by_token(db, token)
    if not signer:
        raise HTTPException(status_code=404, detail="Invalid signing link")
    try:
        doc = services.decline_document(
            db,
            signer.document,
            signer,
            ip_address=_client_ip(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    doc = _load_document(db, doc.id)
    return _document_out(doc, request)
