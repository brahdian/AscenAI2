"""
Inbound channel webhook handlers.

Supported channels:
  POST /channels/{tenant_id}/{agent_id}/whatsapp/webhook    — Meta Business API (WhatsApp)
  GET  /channels/{tenant_id}/{agent_id}/whatsapp/webhook    — WhatsApp webhook verification challenge
  POST /channels/{tenant_id}/{agent_id}/sms/webhook         — Twilio SMS inbound (TwiML)
  POST /channels/{tenant_id}/{agent_id}/slack/events        — Slack Events API
  POST /channels/{tenant_id}/{agent_id}/email/inbound       — SendGrid Inbound Parse

Tenant and agent IDs are embedded in the URL path so that:
  1. External providers (Slack, Twilio, Meta) do not need to inject custom headers.
  2. Each tenant registers their own unique webhook URL.
  3. Messages are deterministically routed without any header guessing.

Cross-channel identity resolution priority: phone → email → channel_id
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from typing import Optional

import httpx
import structlog
from xml.sax.saxutils import escape
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db

logger = structlog.get_logger(__name__)
router = APIRouter()

# Settings pulled from environment — these are GLOBAL defaults and can be
# overridden per-tenant via a future ChannelCredentials DB lookup.
_WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
_WHATSAPP_APP_SECRET = os.getenv("WHATSAPP_APP_SECRET", "")
from app.core.config import settings
_TWILIO_AUTH_TOKEN = settings.TWILIO_AUTH_TOKEN
_SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET", "")
_SENDGRID_WEBHOOK_KEY = os.getenv("SENDGRID_WEBHOOK_KEY", "")
_ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://ai-orchestrator:8000")
_ORCHESTRATOR_INTERNAL_KEY = os.getenv("ORCHESTRATOR_INTERNAL_KEY", "")
_MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://mcp-server:8001")

# Dedup cache TTL (seconds) — prevents duplicate webhook deliveries
# SECURITY: Uses Redis SETNX for constant-time O(1) dedup instead of an in-memory
# dict that could be exhausted by an attacker sending many unique IDs (Slowloris).
_DEDUP_TTL = 300


async def _dedup(message_id: str) -> bool:
    """Return True if this message_id was seen recently (duplicate).

    Uses Redis SETNX to atomically check-and-set in O(1) time.
    Falls back to in-memory allow (not raise) if Redis is unavailable.
    """
    try:
        from app.core.redis_client import get_redis
        redis = await get_redis()
        key = f"webhook_dedup:{message_id}"
        # SETNX: set only if not exists. Returns 1 (new) or 0 (duplicate).
        is_new = await redis.set(key, "1", ex=_DEDUP_TTL, nx=True)
        return not bool(is_new)  # True = duplicate (already existed)
    except Exception:
        # If Redis is down, allow the message through rather than dropping
        return False


async def _forward_to_orchestrator(
    agent_id: str,
    session_id: str,
    message: str,
    customer_identifier: str,
    channel: str,
    tenant_id: str,
) -> Optional[str]:
    """Forward inbound message to the AI orchestrator and return the response text."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{_ORCHESTRATOR_URL}/api/v1/chat",
                json={
                    "agent_id": agent_id,
                    "session_id": session_id,
                    "message": message,
                    "customer_identifier": customer_identifier,
                    "channel": channel,
                    "stream": False,
                },
                headers={
                    "X-Tenant-ID": tenant_id,
                    "X-Internal-Key": _ORCHESTRATOR_INTERNAL_KEY,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("response") or data.get("message") or ""
    except Exception as exc:
        logger.error("orchestrator_forward_error", channel=channel, error=str(exc))
        return None


# ---------------------------------------------------------------------------
# Twilio Pay Webhook
# ---------------------------------------------------------------------------

@router.post("/{tenant_id}/{agent_id}/voice/pay-webhook")
async def twilio_pay_webhook(tenant_id: str, agent_id: str, request: Request):
    """
    Handle Twilio Pay completion callback.
    Verified by X-Twilio-Signature to prevent forgery.
    """
    form_data = await request.form()
    params = dict(form_data)

    # ── 0. Validate Twilio Signature ──────────────────────────────────────────
    from app.core.config import settings
    auth_token = settings.TWILIO_AUTH_TOKEN
    
    if auth_token:
        signature = request.headers.get("X-Twilio-Signature", "")
        # Important: request.url may be internal (http://api-gateway...)
        # We need to use the publicly reachable URL for signature matching.
        # Twilio usually sends the absolute URL it was configured with.
        url = str(request.url)
        if not _validate_twilio_signature(auth_token, signature, url, params):
            logger.warning("twilio_pay_signature_invalid", tenant_id=tenant_id)
            # For hardening, we enforce this.
            raise HTTPException(status_code=403, detail="Invalid Twilio signature")

    result = params.get("Result", "")
    payment_card_type = params.get("PaymentCardType", "")
    payment_card_last4 = params.get("PaymentCardLast4", "")
    transaction_sid = params.get("TransactionSid", "")
    payment_confirmation_code = params.get("PaymentConfirmationCode", "")
    error_code = params.get("ErrorCode", "")
    error_description = params.get("ErrorDescription", "")

    payment_token = params.get("PaymentToken", "")
    if not payment_token:
        logger.warning("twilio_pay_webhook_missing_token", tenant_id=tenant_id)
        twiml = '<?xml version="1.0" encoding="UTF-8"?><Response><Say>Payment session not found. Please try again later.</Say><Hangup/></Response>'
        return Response(content=twiml, media_type="text/xml")

    logger.info(
        "twilio_pay_webhook_received",
        tenant_id=tenant_id,
        agent_id=agent_id,
        payment_token=payment_token,
        result=result,
        card_type=payment_card_type,
        last4=payment_card_last4,
        transaction_sid=transaction_sid,
    )

    # ── 1. Read original session context from Redis ────────────────────────────
    # The twilio_pay_initiate tool stores session data under this key.
    session_id: str | None = None
    customer_identifier: str = tenant_id
    original_session: dict = {}

    try:
        from app.core.redis_client import get_redis

        redis = await get_redis()

        session_raw = await redis.get(f"payment_session:{payment_token}")
        if session_raw:
            original_session = json.loads(session_raw)
            session_id = original_session.get("session_id")
            # Use the customer phone/identifier stored at initiation time
            customer_identifier = original_session.get("customer_identifier", tenant_id)

            # ── SECURITY: IDOR guard — verify the stored session belongs to this tenant
            stored_tenant = original_session.get("tenant_id", "")
            if stored_tenant and stored_tenant != tenant_id:
                logger.warning(
                    "twilio_pay_idor_attempt",
                    url_tenant_id=tenant_id,
                    stored_tenant_id=stored_tenant,
                    payment_token=payment_token,
                )
                raise HTTPException(status_code=403, detail="Payment session does not belong to this tenant")

        # ── 2. Persist the payment result for audit / downstream tooling ───────
        payment_result = {
            "result": result,
            "card_type": payment_card_type,
            "last4": payment_card_last4,
            "transaction_sid": transaction_sid,
            "confirmation_code": payment_confirmation_code,
            "error_code": error_code,
            "error_description": error_description,
            "timestamp": time.time(),
        }

        if original_session:
            original_session["status"] = "success" if result == "Success" else "failed"
            original_session["result_data"] = payment_result
            await redis.set(
                f"payment_session:{payment_token}",
                json.dumps(original_session),
                ex=3600,  # keep result for 1 hr for receipts / lookup
            )

        # Separate result key so other services can poll without re-parsing
        await redis.set(
            f"payment_result:{payment_token}",
            json.dumps(payment_result),
            ex=3600,
        )

    except Exception as exc:
        logger.error(
            "twilio_pay_webhook_redis_error",
            payment_token=payment_token,
            error=str(exc),
        )

    # ── 3. Build system message describing the payment outcome ─────────────────
    # This is injected into the AI conversation so the agent can respond
    # naturally without us hardcoding a canned message.
    if result == "Success":
        system_msg = (
            f"[PAYMENT_RESULT] The customer's payment was successfully processed via Twilio Pay. "
            f"Details — Card: {payment_card_type or 'Unknown'} ending in {payment_card_last4 or 'N/A'}, "
            f"Transaction SID: {transaction_sid or 'N/A'}, "
            f"Confirmation code: {payment_confirmation_code or transaction_sid or 'N/A'}. "
            f"Please acknowledge the successful payment warmly, thank the customer, "
            f"complete any remaining steps (e.g., confirm any booking, offer to send a receipt via SMS), "
            f"and ask if there is anything else you can help with."
        )
    else:
        error_detail = error_description or error_code or "an unexpected error occurred"
        system_msg = (
            f"[PAYMENT_RESULT] The customer's payment attempt failed. "
            f"Error code: {error_code or 'N/A'} — {error_description or 'No further details'}. "
            f"Please tell the customer their payment was not successful in an empathetic, helpful tone. "
            f"Offer to try again with a different card or suggest they call back. "
            f"Do not disclose the raw error code to the customer."
        )

    # ── 4. Re-inject into the AI session ──────────────────────────────────────
    ai_response_text: str | None = None

    if session_id:
        logger.info(
            "twilio_pay_webhook_reinject",
            session_id=session_id,
            result=result,
            agent_id=agent_id,
        )
        try:
            ai_response_text = await _forward_to_orchestrator(
                agent_id=agent_id,
                session_id=session_id,
                message=system_msg,
                customer_identifier=customer_identifier,
                channel="voice",
                tenant_id=tenant_id,
            )
        except Exception as exc:
            logger.error(
                "twilio_pay_webhook_orchestrator_error",
                session_id=session_id,
                payment_token=payment_token,
                error=str(exc),
            )
    else:
        logger.warning(
            "twilio_pay_webhook_no_session",
            payment_token=payment_token,
            note="session_id not found in Redis — using generic fallback response",
        )

    # ── 5. Fallback TTS if orchestrator is unavailable ────────────────────────
    if not ai_response_text:
        if result == "Success":
            card_info = f"your {payment_card_type} card ending in {payment_card_last4}" if payment_card_last4 else "your card"
            conf = payment_confirmation_code or transaction_sid or "N/A"
            ai_response_text = (
                f"Thank you! Your payment was processed successfully using {card_info}. "
                f"Your confirmation number is {conf}. "
                f"Is there anything else I can help you with?"
            )
        else:
            error_detail = error_description or "an unexpected error"
            ai_response_text = (
                f"I'm sorry, your payment could not be processed. {error_detail}. "
                f"You're welcome to try again with a different card, or contact us directly and we'll be happy to assist."
            )

    # ── 6. Return TwiML ───────────────────────────────────────────────────────
    escaped = escape(ai_response_text)

    if result == "Success":
        # On success: say the response and leave the call open
        # (Twilio will hang up when the caller disconnects or the AI says goodbye)
        twiml = f'<?xml version="1.0" encoding="UTF-8"?><Response><Say>{escaped}</Say></Response>'
    else:
        # On failure: say the response then hang up
        twiml = f'<?xml version="1.0" encoding="UTF-8"?><Response><Say>{escaped}</Say><Hangup/></Response>'

    return Response(content=twiml, media_type="text/xml")


def _validate_twilio_signature(
    auth_token: str,
    signature: str,
    url: str,
    params: dict,
) -> bool:
    """Validate Twilio webhook signature."""
    try:
        from twilio.request_validator import RequestValidator  # type: ignore
        validator = RequestValidator(auth_token)
        return validator.validate(url, params, signature)
    except ImportError:
        # If twilio package not installed, fall back to manual HMAC
        sorted_params = "".join(f"{k}{v}" for k, v in sorted(params.items()))
        s = url + sorted_params
        signature_check = hmac.new(
            auth_token.encode(), s.encode(), hashlib.sha1
        ).digest()
        import base64
        expected = base64.b64encode(signature_check).decode()
        return hmac.compare_digest(signature, expected)


@router.post("/{tenant_id}/{agent_id}/sms/webhook")
async def sms_inbound(tenant_id: str, agent_id: str, request: Request):
    """Handle inbound SMS from Twilio. Returns TwiML."""
    form_data = await request.form()
    params = dict(form_data)

    # Validate Twilio signature
    if _TWILIO_AUTH_TOKEN:
        sig = request.headers.get("X-Twilio-Signature", "")
        url = str(request.url)
        if not _validate_twilio_signature(_TWILIO_AUTH_TOKEN, sig, url, params):
            logger.warning("twilio_signature_invalid", tenant_id=tenant_id)
            raise HTTPException(status_code=403, detail="Invalid Twilio signature")

    msg_sid = params.get("MessageSid", "")
    if await _dedup(msg_sid):
        return PlainTextResponse(
            '<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
            media_type="application/xml",
        )

    from_number = params.get("From", "")
    body = params.get("Body", "").strip()

    if not from_number or not body:
        return PlainTextResponse(
            '<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
            media_type="application/xml",
        )

    logger.info("sms_message_received", from_number=from_number, body_length=len(body), tenant_id=tenant_id)

    session_id = f"sms_{from_number}"
    response_text = await _forward_to_orchestrator(
        agent_id=agent_id,
        session_id=session_id,
        message=body,
        customer_identifier=from_number,
        channel="sms",
        tenant_id=tenant_id,
    ) or "Sorry, I'm unable to process your request right now."

    # Return TwiML response
    escaped = escape(response_text)
    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f"<Response><Message>{escaped}</Message></Response>"
    )
    return PlainTextResponse(twiml, media_type="application/xml")


# ---------------------------------------------------------------------------
# Slack Events API
# ---------------------------------------------------------------------------

def _verify_slack_signature(signing_secret: str, body: bytes, headers: dict) -> bool:
    """Verify Slack request signature."""
    timestamp = headers.get("x-slack-request-timestamp", "")
    slack_sig = headers.get("x-slack-signature", "")

    # Reject stale requests (> 5 minutes old)
    try:
        if abs(time.time() - float(timestamp)) > 300:
            return False
    except (ValueError, TypeError):
        return False

    sig_base = f"v0:{timestamp}:{body.decode('utf-8', errors='replace')}"
    computed = "v0=" + hmac.new(
        signing_secret.encode(),
        sig_base.encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(slack_sig, computed)


@router.post("/{tenant_id}/{agent_id}/slack/events")
async def slack_events(tenant_id: str, agent_id: str, request: Request):
    """Handle Slack Events API callbacks (app_mention, message.im)."""
    body_bytes = await request.body()

    if _SLACK_SIGNING_SECRET:
        if not _verify_slack_signature(
            _SLACK_SIGNING_SECRET,
            body_bytes,
            dict(request.headers),
        ):
            logger.warning("slack_signature_invalid", tenant_id=tenant_id)
            raise HTTPException(status_code=403, detail="Invalid Slack signature")

    try:
        payload = json.loads(body_bytes)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # URL verification challenge (one-time during app setup)
    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge")}

    event = payload.get("event", {})
    event_type = event.get("type", "")

    # Only handle app_mention and direct messages
    if event_type not in ("app_mention", "message"):
        return {"status": "ignored"}

    # Ignore bot messages
    if event.get("bot_id") or event.get("subtype"):
        return {"status": "ignored"}

    event_id = payload.get("event_id", "")
    if event_id and await _dedup(event_id):
        return {"status": "duplicate"}

    user_id = event.get("user", "")
    text = event.get("text", "").strip()
    channel_id = event.get("channel", "")

    # Strip bot mention from app_mention events (<@BOTID> some message)
    import re
    text = re.sub(r"<@[A-Z0-9]+>\s*", "", text).strip()

    if not text or not user_id:
        return {"status": "ignored"}

    logger.info("slack_message_received", user_id=user_id, channel_id=channel_id, tenant_id=tenant_id)

    session_id = f"slack_{user_id}_{channel_id}"
    response_text = await _forward_to_orchestrator(
        agent_id=agent_id,
        session_id=session_id,
        message=text,
        customer_identifier=user_id,
        channel="slack",
        tenant_id=tenant_id,
    ) or ""

    # Post response back to Slack
    if response_text:
        slack_token = os.getenv("SLACK_BOT_TOKEN", "")
        if slack_token:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    await client.post(
                        "https://slack.com/api/chat.postMessage",
                        headers={"Authorization": f"Bearer {slack_token}"},
                        json={
                            "channel": channel_id,
                            "text": response_text,
                            "thread_ts": event.get("thread_ts") or event.get("ts"),
                        },
                    )
            except Exception as exc:
                logger.error("slack_reply_error", error=str(exc))

    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Email (SendGrid Inbound Parse)
# ---------------------------------------------------------------------------

@router.post("/{tenant_id}/{agent_id}/email/inbound")
async def email_inbound(tenant_id: str, agent_id: str, request: Request):
    """Handle inbound email via SendGrid Inbound Parse webhook."""
    form_data = await request.form()

    from_email = form_data.get("from", "") or form_data.get("sender", "")
    subject = form_data.get("subject", "")
    text_body = form_data.get("text", "") or form_data.get("html", "")

    # Extract email address from "Name <email@example.com>" format
    import re
    email_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", from_email)
    customer_email = email_match.group(0) if email_match else from_email

    # Compose message text
    message = f"Subject: {subject}\n\n{text_body}".strip()
    if not message or not customer_email:
        return {"status": "ignored"}

    # Dedup by message-id header
    msg_id = form_data.get("headers", "")
    mid_match = re.search(r"Message-ID:\s*<([^>]+)>", msg_id, re.IGNORECASE)
    if mid_match and await _dedup(mid_match.group(1)):
        return {"status": "duplicate"}

    logger.info("email_message_received", from_email=customer_email, subject=subject[:50], tenant_id=tenant_id)

    session_id = f"email_{customer_email.replace('@', '_at_')}"
    await _forward_to_orchestrator(
        agent_id=agent_id,
        session_id=session_id,
        message=message[:4000],  # Limit to avoid oversized payloads
        customer_identifier=customer_email,
        channel="email",
        tenant_id=tenant_id,
    )

    return {"status": "ok"}
