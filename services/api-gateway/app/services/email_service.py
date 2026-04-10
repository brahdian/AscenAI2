from __future__ import annotations

import aiosmtplib
import structlog

from app.core.config import settings

logger = structlog.get_logger(__name__)


async def send_email(to: str, subject: str, html_body: str) -> bool:
    """Send an email using the configured provider (smtp or sendgrid).

    Returns True on success, False on failure.
    """
    provider = settings.EMAIL_PROVIDER.lower()

    if provider == "sendgrid":
        return await _send_via_sendgrid(to, subject, html_body)
    else:
        return await _send_via_smtp(to, subject, html_body)


async def _send_via_sendgrid(to: str, subject: str, html_body: str) -> bool:
    """Send email using SendGrid API."""
    if not settings.SENDGRID_API_KEY:
        logger.warning("sendgrid_api_key_not_configured", to=to)
        return False

    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail

        message = Mail(
            from_email=settings.FROM_EMAIL,
            to_emails=to,
            subject=subject,
            html_content=html_body,
        )
        sg = SendGridAPIClient(settings.SENDGRID_API_KEY)
        response = sg.send(message)
        if 200 <= response.status_code < 300:
            logger.info("sendgrid_email_sent", to=to, status_code=response.status_code)
            return True
        else:
            logger.warning(
                "sendgrid_email_failed",
                to=to,
                status_code=response.status_code,
                body=response.body,
            )
            return False
    except Exception as exc:
        logger.warning("sendgrid_email_failed", to=to, error=str(exc))
        return False


async def _send_via_smtp(to: str, subject: str, html_body: str) -> bool:
    """Send email using SMTP (aiosmtplib)."""
    if not settings.SMTP_HOST:
        logger.warning("smtp_not_configured", to=to)
        return False

    try:
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.FROM_EMAIL
        msg["To"] = to
        msg.attach(MIMEText(html_body, "html"))

        await aiosmtplib.send(
            msg,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USER or None,
            password=settings.SMTP_PASSWORD or None,
            start_tls=settings.SMTP_TLS,
        )
        logger.info("smtp_email_sent", to=to)
        return True
    except Exception as exc:
        logger.warning("smtp_email_failed", to=to, error=str(exc))
        return False
