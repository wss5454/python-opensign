import json
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload

from app.auth import (
    authenticate_admin,
    get_session_admin,
    login_admin,
    logout_admin,
    require_admin_web,
)
from app.config import settings
from app.database import Document, Signer, User, get_db

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
web_router = APIRouter(tags=["web"])


def _ctx(request: Request, admin: User | None = None, **extra):
    data = {
        "request": request,
        "app_name": settings.app_name,
        "admin": admin,
        "admin_name": admin.name if admin else None,
        "sign_workspace": False,
    }
    data.update(extra)
    return data


@web_router.get("/login", response_class=HTMLResponse)
def login_page(
    request: Request,
    next: str = "/",
    admin: User | None = Depends(get_session_admin),
):
    if admin:
        return RedirectResponse(next or "/", status_code=303)
    return templates.TemplateResponse(
        "login.html",
        _ctx(request, error=None, next=next or "/"),
    )


@web_router.post("/login")
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
    db: Session = Depends(get_db),
):
    admin = authenticate_admin(db, email.strip(), password)
    if not admin:
        return templates.TemplateResponse(
            "login.html",
            _ctx(
                request,
                error="Invalid email or password.",
                next=next or "/",
                email=email.strip(),
            ),
            status_code=400,
        )
    login_admin(request, admin)
    target = next if next.startswith("/") else "/"
    return RedirectResponse(target, status_code=303)


@web_router.get("/logout")
def logout(request: Request):
    logout_admin(request)
    return RedirectResponse("/login", status_code=303)


@web_router.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_web),
):
    docs = (
        db.query(Document)
        .options(joinedload(Document.signers))
        .order_by(Document.created_at.desc())
        .all()
    )
    draft_documents = [d for d in docs if d.status == "draft"]
    sent_documents = [d for d in docs if d.status != "draft"]
    out_for = [d for d in docs if d.status in ("sent", "partially_signed")]
    return templates.TemplateResponse(
        "index.html",
        _ctx(
            request,
            admin,
            documents=docs,
            draft_documents=draft_documents,
            sent_documents=sent_documents,
            stats={
                "need_signature": 0,
                "out_for_signatures": len(out_for),
            },
        ),
    )


@web_router.get("/documents", response_class=HTMLResponse)
def documents_list(
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_web),
):
    docs = (
        db.query(Document)
        .options(joinedload(Document.signers))
        .order_by(Document.created_at.desc())
        .all()
    )
    return templates.TemplateResponse(
        "documents.html",
        _ctx(request, admin, documents=docs),
    )


@web_router.get("/api-docs", response_class=HTMLResponse)
def api_docs_page(
    request: Request,
    admin: User = Depends(require_admin_web),
):
    return templates.TemplateResponse(
        "api_docs.html",
        _ctx(request, admin),
    )


@web_router.get("/documents/new", response_class=HTMLResponse)
def new_document(
    request: Request,
    admin: User = Depends(require_admin_web),
):
    return templates.TemplateResponse(
        "new_document.html",
        _ctx(request, admin),
    )


@web_router.get("/documents/{document_id}", response_class=HTMLResponse)
def document_detail(
    document_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin_web),
):
    doc = (
        db.query(Document)
        .options(
            joinedload(Document.signers).joinedload(Signer.widgets),
            joinedload(Document.signers).joinedload(Signer.attachments),
            joinedload(Document.audit_events),
        )
        .filter(Document.id == document_id)
        .first()
    )
    if not doc:
        return templates.TemplateResponse(
            "404.html",
            _ctx(request, admin),
            status_code=404,
        )
    base = str(request.base_url).rstrip("/")
    return templates.TemplateResponse(
        "document_detail.html",
        _ctx(
            request,
            admin,
            document=doc,
            base_url=base,
            document_url=f"{base}/d/{doc.public_token}",
        ),
    )


@web_router.get("/d/{public_token}", response_class=HTMLResponse)
def document_public(public_token: str, request: Request, db: Session = Depends(get_db)):
    doc = (
        db.query(Document)
        .options(joinedload(Document.signers).joinedload(Signer.widgets))
        .filter(Document.public_token == public_token)
        .first()
    )
    if not doc:
        return templates.TemplateResponse(
            "404.html",
            _ctx(request),
            status_code=404,
        )
    base = str(request.base_url).rstrip("/")
    return templates.TemplateResponse(
        "document_public.html",
        _ctx(
            request,
            document=doc,
            base_url=base,
            document_url=f"{base}/d/{doc.public_token}",
        ),
    )


@web_router.get("/sign/{token}", response_class=HTMLResponse)
def sign_page(token: str, request: Request, db: Session = Depends(get_db)):
    signer = (
        db.query(Signer)
        .options(
            joinedload(Signer.widgets),
            joinedload(Signer.attachments),
            joinedload(Signer.document).joinedload(Document.signers),
        )
        .filter(Signer.access_token == token)
        .first()
    )
    if not signer:
        return templates.TemplateResponse(
            "404.html",
            _ctx(request),
            status_code=404,
        )

    from app import services

    services.mark_viewed(db, signer.document, signer, ip_address=None)
    can_sign = services.can_signer_act(signer.document, signer)
    current_phase = services.active_phase(signer.document)
    if getattr(signer, "phase", 0) and current_phase is not None and signer.phase > current_phase:
        wait_message = "You can sign after the customer signatures are complete."
    elif signer.document.sequential:
        wait_message = "This document requires sequential signing. You can sign after previous signers finish."
    else:
        wait_message = "You can sign after previous signers finish."
    widgets = [
        {
            "id": w.id,
            "type": w.type,
            "page": w.page,
            "x": w.x,
            "y": w.y,
            "w": w.w,
            "h": w.h,
        }
        for w in signer.widgets
    ]

    return templates.TemplateResponse(
        "sign.html",
        _ctx(
            request,
            sign_workspace=True,
            signer=signer,
            document=signer.document,
            can_sign=can_sign,
            wait_message=wait_message,
            token=token,
            widgets_json=json.dumps(widgets),
            pdf_url=f"/api/documents/{signer.document.id}/file",
            all_signers=signer.document.signers,
        ),
    )
