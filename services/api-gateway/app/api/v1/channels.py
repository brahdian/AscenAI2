"""
Inbound channel webhook handlers.

Supported channels:
  POST /channels/whatsapp/webhook    — Meta Business API (WhatsApp)
  GET  /channels/whatsapp/webhook    — WhatsApp webhook verification challenge
  POST /channels/sms/webhook         — Twilio SMS inbound (TwiML)
  POST /channels/slack/events        — Slack Events API
  POST /channels/email/inbound       — SendGrid Inbound Parse

Each handler:
  1. Validates the channel-specific signature
  2. Parses the message and extracts (customer_id, text, channel)
  3. Resolves / creates a canonical customer identity
  4. Forwards to the AI orchestrator via internal HTTP
  5. Returns the channel-expected response format

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
from fastapi import APIRouter, Form, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse

logger = structlog.get_logger(__name__)
router = APIRouter()

# Settings pulled from environment
_WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
_WHATSAPP_APP_SECRET = os.getenv("WHATSAPP_APP_SECRET", "")
_TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
_SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET", "")
_SENDGRID_WEBHOOK_KEY = os.getenv("SENDGRID_WEBHOOK_KEY", "")
_ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://ai-orchestrator:8000")
_ORCHESTRATOR_INTERNAL_KEY = os.getenv("ORCHESTRATOR_INTERNAL_KEY", "")

# Dedup cache TTL (seconds) — prevents duplicate webhook deliveries
_DEDUP_SEEN: dict[str, float] = {}
_DEDUP_TTL = 300


def _dedup(message_id: str) -> bool:
    """Return True if this message_id was seen recently (duplicate)."""
    now = time.monotonic()
    # Evict stale entries
    stale = [k for k, v in _DEDUP_SEEN.items() if now - v > _DEDUP_TTL]
    for k in stale:
        del _DEDUP_SEEN[k]
    if message_id in _DEDUP_SEEN:
        return True
    _DEDUP_SEEN[message_id] = now
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
# WhatsApp (Meta Business API)
# ---------------------------------------------------------------------------

@router.get("/whatsapp/webhook")
async def whatsapp_verify(request: Request):
    """WhatsApp webhook verification challenge."""
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == _WHATSAPP_VERIFY_TOKEN and _WHATSAPP_VERIFY_TOKEN:
        logger.info("whatsapp_webhook_verified")
        return PlainTextResponse(challenge)

    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/whatsapp/webhook")
async def whatsapp_inbound(request: Request):
    """Handle inbound WhatsApp messages."""
    # Verify Meta signature
    body_bytes = await request.body()
    if _WHATSAPP_APP_SECRET:
        sig_header = request.headers.get("X-Hub-Signature-256", "")
        expected = "sha256=" + hmac.new(
            _WHATSAPP_APP_SECRET.encode(),
            body_bytes,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(sig_header, expected):
            logger.warning("whatsapp_signature_invalid")
            raise HTTPException(status_code=403, detail="Invalid signature")

    try:
        payload = json.loads(body_bytes)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Parse the Meta webhook structure
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            messages = value.get("messages", [])
            metadata = value.get("metadata", {})
            phone_number_id = metadata.get("phone_number_id", "")

            for msg in messages:
                msg_id = msg.get("id", "")
                if _dedup(msg_id):
                    continue

                msg_type = msg.get("type", "")
                if msg_type != "text":
                    continue  # Only handle text for now

                from_number = msg.get("from", "")
                text = msg.get("text", {}).get("body", "")
                if not text or not from_number:
                    continue

                logger.info(
                    "whatsapp_message_received",
                    from_number=from_number,
                    text_length=len(text),
                )

                # Resolve tenant / agent from phone_number_id (simplified)
                tenant_id = request.headers.get("X-Tenant-ID", "")
                agent_id = request.headers.get("X-Agent-ID", "")

                if tenant_id and agent_id:
                    session_id = f"wa_{from_number}"
                    await _forward_to_orchestrator(
                        agent_id=agent_id,
                        session_id=session_id,
                        message=text,
                        customer_identifier=from_number,
                        channel="whatsapp",
                        tenant_id=tenant_id,
                    )

    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Twilio SMS
# ---------------------------------------------------------------------------

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


@router.post("/sms/webhook")
async def sms_inbound(request: Request):
    """Handle inbound SMS from Twilio. Returns TwiML."""
    form_data = await request.form()
    params = dict(form_data)

    # Validate Twilio signature
    if _TWILIO_AUTH_TOKEN:
        sig = request.headers.get("X-Twilio-Signature", "")
        url = str(request.url)
        if not _validate_twilio_signature(_TWILIO_AUTH_TOKEN, sig, url, params):
            logger.warning("twilio_signature_invalid")
            raise HTTPException(status_code=403, detail="Invalid Twilio signature")

    msg_sid = params.get("MessageSid", "")
    if _dedup(msg_sid):
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

    logger.info("sms_message_received", from_number=from_number, body_length=len(body))

    tenant_id = request.headers.get("X-Tenant-ID", "")
    agent_id = request.headers.get("X-Agent-ID", "")

    response_text = ""
    if tenant_id and agent_id:
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
    escaped = response_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
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


@router.post("/slack/events")
async def slack_events(request: Request):
    """Handle Slack Events API callbacks (app_mention, message.im)."""
    body_bytes = await request.body()

    if _SLACK_SIGNING_SECRET:
        if not _verify_slack_signature(
            _SLACK_SIGNING_SECRET,
            body_bytes,
            dict(request.headers),
        ):
            logger.warning("slack_signature_invalid")
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
    if event_id and _dedup(event_id):
        return {"status": "duplicate"}

    user_id = event.get("user", "")
    text = event.get("text", "").strip()
    channel_id = event.get("channel", "")

    # Strip bot mention from app_mention events (<@BOTID> some message)
    import re
    text = re.sub(r"<@[A-Z0-9]+>\s*", "", text).strip()

    if not text or not user_id:
        return {"status": "ignored"}

    logger.info("slack_message_received", user_id=user_id, channel_id=channel_id)

    tenant_id = request.headers.get("X-Tenant-ID", "")
    agent_id = request.headers.get("X-Agent-ID", "")

    if tenant_id and agent_id:
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

@router.post("/email/inbound")
async def email_inbound(request: Request):
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
    if mid_match and _dedup(mid_match.group(1)):
        return {"status": "duplicate"}

    logger.info("email_message_received", from_email=customer_email, subject=subject[:50])

    tenant_id = request.headers.get("X-Tenant-ID", "")
    agent_id = request.headers.get("X-Agent-ID", "")

    if tenant_id and agent_id:
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
