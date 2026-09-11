"""SMTP email helpers for signature invitations."""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.config import settings

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates" / "emails"
_jinja = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)


class MailError(Exception):
    """Raised when mail cannot be sent."""


def resolve_base_url(request_base_url: Optional[str] = None) -> str:
    """Prefer configured public URL; fall back to the current request origin."""
    configured = (settings.public_base_url or "").strip().rstrip("/")
    if configured:
        return configured
    if request_base_url:
        return str(request_base_url).rstrip("/")
    raise MailError(
        "No public base URL available. Set WALLACESIGN_PUBLIC_BASE_URL "
        "or call send while handling an HTTP request."
    )


def sign_url_for(access_token: str, base_url: str) -> str:
    return f"{base_url.rstrip('/')}/sign/{access_token}"


def document_url_for(public_token: str, base_url: str) -> str:
    return f"{base_url.rstrip('/')}/d/{public_token}"


def _build_message(
    *,
    to_email: str,
    to_name: str,
    subject: str,
    text_body: str,
    html_body: str,
) -> EmailMessage:
    msg = EmailMessage()
    from_name = (settings.mail_from_name or "").strip()
    from_addr = (settings.mail_from or settings.smtp_user or "").strip()
    if not from_addr:
        raise MailError("WALLACESIGN_MAIL_FROM (or SMTP user) is not configured")

    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{from_addr}>" if from_name else from_addr
    msg["To"] = f"{to_name} <{to_email}>" if to_name else to_email
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")
    return msg


def send_email(
    *,
    to_email: str,
    to_name: str,
    subject: str,
    text_body: str,
    html_body: str,
) -> None:
    if not settings.mail_enabled:
        logger.info("Mail disabled; skipped email to %s (%s)", to_email, subject)
        return

    host = (settings.smtp_host or "").strip()
    user = (settings.smtp_user or "").strip()
    password = settings.smtp_password or ""
    if not host:
        raise MailError("WALLACESIGN_SMTP_HOST is not configured")
    if not user or not password:
        raise MailError("WALLACESIGN_SMTP_USER / WALLACESIGN_SMTP_PASSWORD are not configured")

    msg = _build_message(
        to_email=to_email,
        to_name=to_name,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
    )

    try:
        if settings.smtp_use_ssl:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, settings.smtp_port, context=context, timeout=30) as smtp:
                smtp.login(user, password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(host, settings.smtp_port, timeout=30) as smtp:
                smtp.ehlo()
                if settings.smtp_use_tls:
                    context = ssl.create_default_context()
                    smtp.starttls(context=context)
                    smtp.ehlo()
                smtp.login(user, password)
                smtp.send_message(msg)
    except MailError:
        raise
    except Exception as exc:
        logger.exception("SMTP send failed to %s", to_email)
        raise MailError(f"Failed to send email to {to_email}: {exc}") from exc

    logger.info("Sent email to %s: %s", to_email, subject)


def _customer_first_name(signer_name: str) -> str:
    parts = (signer_name or "").strip().split()
    return parts[0] if parts else "customer"


def _dealership_name() -> str:
    return (settings.mail_from_name or "").strip() or "your dealership"


def send_signature_request(
    *,
    signer_name: str,
    signer_email: str,
    document_title: str,
    sign_url: str,
    document_url: Optional[str] = None,
) -> None:
    """Send the Wallace eSign signature invitation email."""
    del document_title, document_url  # kept for API compatibility

    first_name = _customer_first_name(signer_name)
    dealership = _dealership_name()
    subject = "Your contract is ready for signature"

    text_body = "\n".join(
        [
            f"Hi {first_name},",
            "",
            f"Your contract for {dealership} is ready for review. "
            "Please review and sign electronically to keep your reservation "
            "active for the upcoming season.",
            "",
            "Review & Sign:",
            sign_url,
            "",
            "This link is unique to you — please don't forward this email. "
            "If you have questions about your renewal, contact your "
            "dealership's office directly.",
            "",
            "Signing made easy!",
        ]
    )

    html_body = _jinja.get_template("signature_request.html").render(
        customer_first_name=first_name,
        dealership_name=dealership,
        sign_url=sign_url,
    )

    send_email(
        to_email=signer_email,
        to_name=signer_name or "",
        subject=subject,
        text_body=text_body,
        html_body=html_body,
    )
