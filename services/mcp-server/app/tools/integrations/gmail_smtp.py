"""Gmail / SMTP email integration handler."""
from __future__ import annotations

import asyncio
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

GMAIL_SEND_EMAIL_SCHEMA = {
    "type": "object",
    "required": ["to", "subject", "body"],
    "properties": {
        "to": {"type": "string", "description": "Recipient email address"},
        "subject": {"type": "string", "description": "Email subject line"},
        "body": {"type": "string", "description": "Email body (plain text)"},
        "html_body": {"type": "string", "description": "Optional HTML version of the body"},
    },
}


def _send_smtp(tenant_config: dict, to: str, subject: str, body: str, html_body: str | None) -> dict:
    """Blocking SMTP send — called in a thread executor."""
    host = tenant_config.get("smtp_host", "smtp.gmail.com")
    port = int(tenant_config.get("smtp_port", 587))
    user = tenant_config.get("smtp_user", "")
    password = tenant_config.get("smtp_password", "")
    from_email = tenant_config.get("from_email", user)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = to

    msg.attach(MIMEText(body, "plain"))
    if html_body:
        msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(host, port, timeout=15) as server:
        server.ehlo()
        server.starttls()
        server.login(user, password)
        server.sendmail(from_email, [to], msg.as_string())

    return {"sent": True, "to": to, "subject": subject}


async def handle_gmail_send_email(parameters: dict, tenant_config: dict) -> dict:
    """Send an email via SMTP."""
    smtp_user = tenant_config.get("smtp_user", "")
    smtp_password = tenant_config.get("smtp_password", "")
    smtp_host = tenant_config.get("smtp_host", "")

    if not smtp_user or not smtp_password or not smtp_host:
        return {"error": "Email not configured. Add SMTP host, username, and password."}

    to = parameters["to"]
    subject = parameters["subject"]
    body = parameters["body"]
    html_body = parameters.get("html_body")

    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            None, _send_smtp, tenant_config, to, subject, body, html_body
        )
    except smtplib.SMTPAuthenticationError:
        return {"error": "SMTP authentication failed. Check your username and app password."}
    except smtplib.SMTPException as exc:
        return {"error": f"SMTP error: {exc}"}
    except Exception as exc:
        return {"error": f"Failed to send email: {exc}"}

    return result
