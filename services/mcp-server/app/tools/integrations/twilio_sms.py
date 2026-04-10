"""Twilio SMS integration handler."""
from __future__ import annotations

import httpx

TWILIO_SMS_SCHEMA = {
    "type": "object",
    "required": ["to", "message"],
    "properties": {
        "to": {
            "type": "string",
            "description": "Recipient phone number in E.164 format, e.g. +16135551234",
        },
        "message": {"type": "string", "description": "SMS message body (max 1600 chars)"},
    },
}


async def handle_twilio_send_sms(parameters: dict, tenant_config: dict) -> dict:
    """Send an SMS via Twilio."""
    account_sid = tenant_config.get("account_sid", "")
    auth_token = tenant_config.get("auth_token", "")
    from_number = tenant_config.get("from_number", "")

    if not account_sid or not auth_token or not from_number:
        return {
            "error": "Twilio not configured. Add your Account SID, Auth Token, and From number."
        }

    to = parameters["to"]
    body = parameters["message"][:1600]

    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
    async with httpx.AsyncClient(timeout=15, auth=(account_sid, auth_token)) as client:
        resp = await client.post(url, data={"To": to, "From": from_number, "Body": body})

    if not resp.is_success:
        data = resp.json()
        return {"error": data.get("message", f"Twilio error {resp.status_code}")}

    msg = resp.json()
    return {
        "sid": msg["sid"],
        "status": msg["status"],
        "to": msg["to"],
        "from": msg["from"],
        "sent": True,
    }
