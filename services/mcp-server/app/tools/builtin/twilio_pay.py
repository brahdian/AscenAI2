"""Built-in Twilio Pay tool handler for collecting credit card payments via DTMF."""
from __future__ import annotations

import json
import uuid
from xml.sax.saxutils import quoteattr

import structlog

logger = structlog.get_logger(__name__)

TWILIO_PAY_SCHEMA = {
    "type": "object",
    "required": ["amount_cents", "currency", "description", "session_id", "call_sid"],
    "properties": {
        "amount_cents": {
            "type": "integer",
            "minimum": 50,
            "description": "Payment amount in cents (minimum 50 cents)",
        },
        "currency": {
            "type": "string",
            "description": "ISO 4217 currency code (e.g., USD, EUR, GBP)",
        },
        "description": {
            "type": "string",
            "maxLength": 255,
            "description": "Description of the charge shown to the caller",
        },
        "session_id": {
            "type": "string",
            "description": "Current voice session identifier (used to resume AI conversation after payment)",
        },
        "call_sid": {
            "type": "string",
            "description": "Twilio Call SID",
        },
        "customer_identifier": {
            "type": "string",
            "description": "Customer phone number or identifier for session recovery (optional)",
        },
    },
}

SUPPORTED_CURRENCIES = {"USD", "EUR", "GBP", "CAD", "AUD"}


async def handle_twilio_pay(parameters: dict, tenant_config: dict) -> dict:
    """Generate TwiML with <Pay> verb for credit card collection via DTMF.

    Stores payment session metadata in Redis for later retrieval by the
    pay-webhook endpoint.  Actual card capture is handled entirely by
    Twilio's <Pay> verb.
    """
    amount_cents = int(parameters["amount_cents"])
    currency = parameters.get("currency", "USD").upper()
    description = parameters.get("description", "")
    session_id = parameters.get("session_id", "")
    call_sid = parameters.get("call_sid", "")

    if not all([amount_cents, session_id, call_sid]):
        return {
            "success": False,
            "error": "Missing required parameters: amount_cents, session_id, call_sid",
        }

    if currency not in SUPPORTED_CURRENCIES:
        return {
            "success": False,
            "error": f"Unsupported currency: {currency}. Supported: {SUPPORTED_CURRENCIES}",
        }

    payment_token = f"pay_{uuid.uuid4().hex}"

    api_base = tenant_config.get("API_GATEWAY_URL", "http://api-gateway:8000")
    tenant_id = tenant_config.get("TENANT_ID", "")
    agent_id = tenant_config.get("AGENT_ID", "")
    pay_connector = tenant_config.get("TWILIO_PAY_CONNECTOR", "default")

    webhook_url = (
        f"{api_base}/channels/{tenant_id}/{agent_id}/voice/pay-webhook"
        if api_base and tenant_id and agent_id
        else None
    )

    payment_data = {
        "payment_token": payment_token,
        "amount_cents": amount_cents,
        "currency": currency,
        "description": description,
        "session_id": session_id,
        "call_sid": call_sid,
        "tenant_id": tenant_id,
        "agent_id": agent_id,
        "customer_identifier": parameters.get("customer_identifier", ""),
        "status": "pending",
    }

    redis_client = tenant_config.get("redis_client")
    if redis_client:
        try:
            await redis_client.set(
                f"payment_session:{payment_token}",
                json.dumps(payment_data),
                ex=600,
            )
            logger.info(
                "twilio_pay_session_created",
                payment_token=payment_token,
                amount_cents=amount_cents,
                currency=currency,
                call_sid=call_sid,
            )
        except Exception as exc:
            logger.error(
                "twilio_pay_redis_error",
                payment_token=payment_token,
                error=str(exc),
            )
            return {
                "success": False,
                "error": "Failed to create payment session",
            }
    else:
        logger.warning(
            "twilio_pay_no_redis",
            payment_token=payment_token,
            note="Payment session not persisted — webhook will not receive result",
        )

    amount_display = f"{amount_cents / 100:.2f}"

    if webhook_url:
        action_attr = f'action="{webhook_url}"'
        redirect_url = f"{api_base}/channels/{tenant_id}/{agent_id}/voice/webhook"
    else:
        action_attr = 'action="/voice/pay-webhook"'
        redirect_url = "/voice/webhook"

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Pay
    {action_attr}
    paymentConnector={quoteattr(pay_connector)}
    chargeAmount={quoteattr(amount_display)}
    currency={quoteattr(currency)}
    description={quoteattr(description)}
    paymentMethod="credit-card"
  >
  </Pay>
  <Redirect>{redirect_url}</Redirect>
</Response>"""

    return {
        "success": True,
        "payment_token": payment_token,
        "twiml": twiml,
        "amount_cents": amount_cents,
        "currency": currency,
        "description": description,
        "webhook_url": webhook_url,
        "instructions": (
            "Return the TwiML to Twilio.  Twilio will collect card details "
            "via DTMF and POST the result to the pay-webhook endpoint."
        ),
    }
