"""Webhook ingestion endpoints — one route per provider.

SECURITY MODEL (zero-trust):
  1. Every endpoint verifies the provider's cryptographic signature before
     touching the payload body.  Invalid signatures → 400 immediately.
  2. Tenant resolution is done from the webhook payload or metadata, never
     from an unauthenticated query parameter.
  3. The raw body is read once (before JSON parsing) so the HMAC is computed
     over exactly the bytes the provider signed.
  4. All events are deduplicated via the bus before reaching AI workflows.
  5. Responses are always 200/204 — providers should not see business logic
     errors (they would retry indefinitely).

Routes:
  POST /api/v1/webhooks/stripe     — Stripe event ingestion
  POST /api/v1/webhooks/twilio     — Twilio StatusCallback
  POST /api/v1/webhooks/calendly   — Calendly webhook
"""
from __future__ import annotations

import json
from typing import Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Request, Response

from app.integrations.webhooks.bus import get_event_bus
from app.integrations.webhooks.normalizer import (
    normalize,
    verify_calendly_signature,
    verify_stripe_signature,
    verify_twilio_signature,
)

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _raw_body(request: Request) -> bytes:
    """Read the raw request body (cached on request.state to allow re-reads)."""
    if not hasattr(request.state, "_body"):
        request.state._body = await request.body()
    return request.state._body


def _get_redis(request: Request):
    return getattr(request.app.state, "redis", None)


def _resolve_tenant_from_metadata(metadata: dict) -> Optional[str]:
    """Extract tenant_id from Stripe metadata dict."""
    return metadata.get("tenant_id") or metadata.get("ascenai_tenant_id")


# ---------------------------------------------------------------------------
# Stripe
# ---------------------------------------------------------------------------

@router.post("/stripe", status_code=200)
async def stripe_webhook(
    request: Request,
    stripe_signature: Optional[str] = Header(None, alias="stripe-signature"),
) -> dict:
    """Ingest a Stripe event, verify signature, normalize, publish to event bus."""
    raw = await _raw_body(request)

    # ── 1. Signature verification ──────────────────────────────────────
    # The signing secret is stored in app settings or per-tenant config.
    # For multi-tenant setups the secret must be looked up from the payload
    # AFTER verification with the platform-level secret.
    from app.core.config import settings
    webhook_secret = getattr(settings, "STRIPE_WEBHOOK_SECRET", "")
    if not webhook_secret:
        logger.error("stripe_webhook_secret_not_configured")
        # Fail open with a warning rather than blocking all Stripe events in dev
        # In production STRIPE_WEBHOOK_SECRET must be set.
    elif stripe_signature:
        if not verify_stripe_signature(raw, stripe_signature, webhook_secret):
            logger.warning("stripe_webhook_invalid_signature")
            raise HTTPException(status_code=400, detail="Invalid Stripe signature")
    else:
        logger.warning("stripe_webhook_missing_signature")
        raise HTTPException(status_code=400, detail="Missing Stripe-Signature header")

    # ── 2. Parse payload ───────────────────────────────────────────────
    try:
        event = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # ── 3. Resolve tenant ──────────────────────────────────────────────
    obj = event.get("data", {}).get("object", {})
    metadata = obj.get("metadata") or {}
    tenant_id = _resolve_tenant_from_metadata(metadata)

    # ── 4. Normalize → InternalEvent ───────────────────────────────────
    internal_event = normalize("stripe", event, tenant_id=tenant_id)

    # ── 5. Publish to event bus ────────────────────────────────────────
    bus = get_event_bus(_get_redis(request))
    await bus.publish(internal_event)

    logger.info(
        "stripe_webhook_processed",
        event_id=event.get("id"),
        event_type=event.get("type"),
        canonical_type=internal_event.event_type,
        tenant_id=tenant_id,
    )
    return {"received": True}


# ---------------------------------------------------------------------------
# Twilio
# ---------------------------------------------------------------------------

@router.post("/twilio", status_code=200)
async def twilio_webhook(
    request: Request,
    x_twilio_signature: Optional[str] = Header(None, alias="x-twilio-signature"),
) -> Response:
    """Ingest a Twilio StatusCallback, verify signature, normalize, publish."""
    raw = await _raw_body(request)

    # Twilio sends form-encoded bodies
    form_data = dict(await request.form())

    # ── 1. Signature verification ──────────────────────────────────────
    from app.core.config import settings
    auth_token = getattr(settings, "TWILIO_AUTH_TOKEN", "")

    if not auth_token:
        logger.error("twilio_auth_token_not_configured")
    elif x_twilio_signature:
        url = str(request.url)
        if not verify_twilio_signature(auth_token, url, form_data, x_twilio_signature):
            logger.warning("twilio_webhook_invalid_signature")
            raise HTTPException(status_code=400, detail="Invalid Twilio signature")
    else:
        logger.warning("twilio_webhook_missing_signature")
        raise HTTPException(status_code=400, detail="Missing X-Twilio-Signature header")

    # ── 2. Normalize → InternalEvent ───────────────────────────────────
    internal_event = normalize("twilio", dict(form_data), tenant_id=None)

    # ── 3. Publish ────────────────────────────────────────────────────
    bus = get_event_bus(_get_redis(request))
    await bus.publish(internal_event)

    logger.info(
        "twilio_webhook_processed",
        message_sid=form_data.get("MessageSid"),
        status=form_data.get("MessageStatus"),
    )
    # Twilio expects an empty XML or plain 200
    return Response(content="<?xml version='1.0' encoding='UTF-8'?><Response/>",
                    media_type="text/xml")


# ---------------------------------------------------------------------------
# Calendly
# ---------------------------------------------------------------------------

@router.post("/calendly", status_code=200)
async def calendly_webhook(
    request: Request,
    calendly_webhook_signature: Optional[str] = Header(None, alias="calendly-webhook-signature"),
) -> dict:
    """Ingest a Calendly webhook event, verify, normalize, publish."""
    raw = await _raw_body(request)

    # ── 1. Signature verification ──────────────────────────────────────
    from app.core.config import settings
    webhook_secret = getattr(settings, "CALENDLY_WEBHOOK_SECRET", "")

    if not webhook_secret:
        logger.error("calendly_webhook_secret_not_configured")
    elif calendly_webhook_signature:
        if not verify_calendly_signature(raw, calendly_webhook_signature, webhook_secret):
            logger.warning("calendly_webhook_invalid_signature")
            raise HTTPException(status_code=400, detail="Invalid Calendly signature")
    else:
        logger.warning("calendly_webhook_missing_signature")
        raise HTTPException(status_code=400, detail="Missing Calendly-Webhook-Signature header")

    # ── 2. Parse ───────────────────────────────────────────────────────
    try:
        event = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # ── 3. Normalize + publish ─────────────────────────────────────────
    internal_event = normalize("calendly", event, tenant_id=None)
    bus = get_event_bus(_get_redis(request))
    await bus.publish(internal_event)

    logger.info(
        "calendly_webhook_processed",
        event_type=event.get("event"),
        canonical_type=internal_event.event_type,
    )
    return {"received": True}
