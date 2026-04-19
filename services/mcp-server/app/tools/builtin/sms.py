"""Built-in SMS sending tool handler."""
from __future__ import annotations

import re
import structlog

logger = structlog.get_logger(__name__)

_E164_PATTERN = re.compile(r"^\+[1-9]\d{1,14}$")

SMS_SEND_SCHEMA = {
    "type": "object",
    "required": ["to", "message"],
    "properties": {
        "to": {"type": "string", "description": "Recipient phone number (E.164 format)"},
        "message": {"type": "string", "maxLength": 1600},
    },
}


async def handle_send_sms(parameters: dict, tenant_config: dict) -> dict:
    """Send an SMS via Twilio or log it for testing."""
    to = parameters.get("to", "")
    message = parameters.get("message", "")

    masked_to = f"{to[:4]}...{to[-2:]}" if len(to) > 6 else "***"

    if not to or not message:
        return {"success": False, "error": "Missing required parameters: to, message"}

    if not _E164_PATTERN.match(to):
        return {"success": False, "error": f"Invalid phone number format. Must be E.164 (e.g. +14155551234). Got: {to}"}

    account_sid = tenant_config.get("twilio_account_sid") or tenant_config.get("TWILIO_ACCOUNT_SID")
    auth_token = tenant_config.get("twilio_auth_token") or tenant_config.get("TWILIO_AUTH_TOKEN")
    from_number = tenant_config.get("twilio_phone_number") or tenant_config.get("TWILIO_FROM_NUMBER")

    if not all([account_sid, auth_token, from_number]):
        # Dev mode — log and return success
        logger.info("sms_dev_mode", to=masked_to, message=message[:50])
        return {
            "success": True,
            "sid": "TEST_SID",
            "status": "queued",
            "to": to,
            "message": "(dev mode) SMS logged, not sent.",
        }

    try:
        from twilio.rest import Client  # type: ignore

        client = Client(account_sid, auth_token)
        msg = client.messages.create(to=to, from_=from_number, body=message)
        return {
            "success": True,
            "sid": msg.sid,
            "status": msg.status,
            "to": to,
        }
    except Exception as exc:
        logger.error("sms_send_failed", to=masked_to, error=str(exc))
        return {"success": False, "error": str(exc), "to": to}
