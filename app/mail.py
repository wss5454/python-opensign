"""SMTP email helpers for signature invitations."""

from __future__ import annotations

import html
import logging
import smtplib
import ssl
from email.message import EmailMessage
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


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


def send_signature_request(
    *,
    signer_name: str,
    signer_email: str,
    document_title: str,
    sign_url: str,
    document_url: Optional[str] = None,
) -> None:
    subject = f"Please sign: {document_title}"
    text_lines = [
        f"Hi {signer_name},",
        "",
        f'You have been asked to sign "{document_title}".',
        "",
        f"Open this link to review and sign:",
        sign_url,
    ]
    if document_url:
        text_lines.extend(["", f"Document status: {document_url}"])
    text_lines.extend(
        [
            "",
            "If you were not expecting this request, you can ignore this email.",
            "",
            f"— {settings.mail_from_name or settings.app_name}",
        ]
    )
    text_body = "\n".join(text_lines)

    safe_name = html.escape(signer_name)
    safe_title = html.escape(document_title)
    safe_brand = html.escape(settings.mail_from_name or settings.app_name)
    safe_sign_url = html.escape(sign_url, quote=True)
    safe_sign_url_text = html.escape(sign_url)
    doc_status_html = ""
    if document_url:
        safe_doc_url = html.escape(document_url, quote=True)
        doc_status_html = (
            f'<p style="margin:16px 0 0;font-size:14px;color:#4b5563;">'
            f'<a href="{safe_doc_url}" style="color:#1e3a5f;">View document status</a></p>'
        )
    html_body = f"""\
<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#f3f4f6;font-family:Arial,Helvetica,sans-serif;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f3f4f6;padding:24px 12px;">
    <tr>
      <td align="center">
        <table role="presentation" width="560" cellspacing="0" cellpadding="0" style="background:#ffffff;border-radius:8px;padding:28px 24px;">
          <tr>
            <td style="font-size:20px;font-weight:700;color:#1e3a5f;">
              {safe_brand}
            </td>
          </tr>
          <tr>
            <td style="padding-top:20px;font-size:16px;line-height:1.5;color:#111827;">
              Hi {safe_name},
            </td>
          </tr>
          <tr>
            <td style="padding-top:12px;font-size:16px;line-height:1.5;color:#111827;">
              You have been asked to sign <strong>{safe_title}</strong>.
            </td>
          </tr>
          <tr>
            <td style="padding-top:24px;" align="center">
              <a href="{safe_sign_url}"
                 style="display:inline-block;background:#1e3a5f;color:#ffffff;text-decoration:none;
                        padding:12px 22px;border-radius:6px;font-size:15px;font-weight:600;">
                Review and sign
              </a>
            </td>
          </tr>
          <tr>
            <td style="padding-top:18px;font-size:13px;line-height:1.5;color:#6b7280;word-break:break-all;">
              Or copy this link:<br />{safe_sign_url_text}
            </td>
          </tr>
          <tr>
            <td>{doc_status_html}</td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""
    send_email(
        to_email=signer_email,
        to_name=signer_name,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
    )
