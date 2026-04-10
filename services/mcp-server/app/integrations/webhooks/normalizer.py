"""Webhook event normalizer — maps provider-native events to InternalEvents.

DESIGN:
  Every provider delivers webhooks in its own schema.  This module hides all
  provider specifics.  The rest of the platform only ever sees InternalEvent.

Event flow:
  Provider → receiver.py → normalizer.py → bus.py → AI workflow triggers

Versioning:
  InternalEvent carries a `schema_version` field.  Increment it when the
  output shape changes.  Consumers should check this before parsing `payload`.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)

_SCHEMA_VERSION = "1.0"


# ---------------------------------------------------------------------------
# InternalEvent — the canonical event type all consumers receive
# ---------------------------------------------------------------------------

@dataclass
class InternalEvent:
    """Normalized, versioned event emitted onto the internal bus.

    Fields
    ------
    event_type:
        Canonical event name (see EVENT_TYPE_* constants below).
    provider:
        Source provider, e.g. "stripe", "calendly".
    schema_version:
        Schema version for forward-compatibility.
    tenant_id:
        Resolved from webhook metadata or signature verification.
        May be None for providers that don't embed tenant info.
    payload:
        Normalized payload — never contains provider-native field names.
    occurred_at:
        When the event occurred (from provider timestamp or now()).
    raw_event:
        Original provider payload — stored for replay / debugging only,
        never exposed to the AI layer.
    idempotency_key:
        Unique key to deduplicate re-delivered webhooks (provider event ID).
    """
    event_type: str
    provider: str
    schema_version: str
    tenant_id: Optional[str]
    payload: dict[str, Any]
    occurred_at: datetime
    raw_event: dict[str, Any]
    idempotency_key: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type,
            "provider": self.provider,
            "schema_version": self.schema_version,
            "tenant_id": self.tenant_id,
            "payload": self.payload,
            "occurred_at": self.occurred_at.isoformat(),
            "idempotency_key": self.idempotency_key,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# Canonical event type constants
# ---------------------------------------------------------------------------

class EventType:
    # Payment events
    PAYMENT_COMPLETED   = "PaymentCompleted"
    PAYMENT_FAILED      = "PaymentFailed"
    PAYMENT_REFUNDED    = "PaymentRefunded"
    SUBSCRIPTION_CREATED = "SubscriptionCreated"
    SUBSCRIPTION_CANCELLED = "SubscriptionCancelled"

    # Scheduling events
    MEETING_SCHEDULED   = "MeetingScheduled"
    MEETING_CANCELLED   = "MeetingCancelled"
    MEETING_RESCHEDULED = "MeetingRescheduled"

    # Messaging events
    SMS_DELIVERED       = "SMSDelivered"
    SMS_FAILED          = "SMSFailed"

    # Generic
    UNKNOWN             = "UnknownEvent"


# ---------------------------------------------------------------------------
# Signature verification helpers
# ---------------------------------------------------------------------------

def verify_stripe_signature(
    payload_bytes: bytes,
    signature_header: str,
    secret: str,
    tolerance_seconds: int = 300,
) -> bool:
    """Verify a Stripe webhook signature (Stripe-Signature header).

    Uses the same algorithm as the official Stripe SDK but without the
    dependency, so it works even if stripe is not installed.
    """
    try:
        parts = {k: v for k, v in (p.split("=", 1) for p in signature_header.split(",") if "=" in p)}
        timestamp = int(parts.get("t", "0"))
        signatures = [v for k, v in parts.items() if k == "v1"]

        # Reject stale webhooks
        if abs(time.time() - timestamp) > tolerance_seconds:
            logger.warning("stripe_webhook_timestamp_stale", age_seconds=abs(time.time() - timestamp))
            return False

        signed_payload = f"{timestamp}.".encode() + payload_bytes
        expected = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
        return any(hmac.compare_digest(expected, sig) for sig in signatures)
    except Exception as exc:
        logger.warning("stripe_signature_verify_error", error=str(exc))
        return False


def verify_twilio_signature(
    auth_token: str,
    url: str,
    post_params: dict,
    signature: str,
) -> bool:
    """Verify a Twilio webhook signature (X-Twilio-Signature header)."""
    try:
        from twilio.request_validator import RequestValidator
        validator = RequestValidator(auth_token)
        return validator.validate(url, post_params, signature)
    except ImportError:
        # Manual fallback if twilio SDK not available
        # Build the string: url + sorted POST param key+values concatenated
        s = url + "".join(f"{k}{v}" for k, v in sorted(post_params.items()))
        expected = hmac.new(auth_token.encode(), s.encode(), hashlib.sha1).digest()
        import base64
        return hmac.compare_digest(base64.b64encode(expected).decode(), signature)
    except Exception as exc:
        logger.warning("twilio_signature_verify_error", error=str(exc))
        return False


def verify_calendly_signature(
    payload_bytes: bytes,
    signature_header: str,
    secret: str,
    tolerance_seconds: int = 300,
) -> bool:
    """Verify a Calendly webhook signature (Calendly-Webhook-Signature header)."""
    try:
        # Format: "t=<timestamp>,v1=<signature>"
        parts = dict(p.split("=", 1) for p in signature_header.split(",") if "=" in p)
        timestamp = parts.get("t", "")
        v1 = parts.get("v1", "")

        if not timestamp or not v1:
            return False

        ts = int(timestamp)
        if abs(time.time() - ts) > tolerance_seconds:
            return False

        signed = f"{timestamp}.".encode() + payload_bytes
        expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, v1)
    except Exception as exc:
        logger.warning("calendly_signature_verify_error", error=str(exc))
        return False


# ---------------------------------------------------------------------------
# Provider-specific event normalizers
# ---------------------------------------------------------------------------

def _normalize_stripe(event: dict, tenant_id: Optional[str]) -> InternalEvent:
    """Map a Stripe event dict to an InternalEvent."""
    event_type = event.get("type", "")
    obj = event.get("data", {}).get("object", {})

    type_map: dict[str, str] = {
        "payment_intent.succeeded":          EventType.PAYMENT_COMPLETED,
        "payment_intent.payment_failed":     EventType.PAYMENT_FAILED,
        "charge.refunded":                   EventType.PAYMENT_REFUNDED,
        "customer.subscription.created":     EventType.SUBSCRIPTION_CREATED,
        "customer.subscription.deleted":     EventType.SUBSCRIPTION_CANCELLED,
    }
    canonical_type = type_map.get(event_type, EventType.UNKNOWN)

    # Normalized payload — no Stripe field names exposed
    payload: dict[str, Any] = {
        "provider_event_id": event.get("id"),
        "provider_event_type": event_type,
    }

    if canonical_type == EventType.PAYMENT_COMPLETED:
        payload.update({
            "payment_id": obj.get("id"),
            "amount": (obj.get("amount", 0)) / 100.0,
            "currency": obj.get("currency", ""),
            "customer_email": obj.get("receipt_email") or (obj.get("charges", {}).get("data", [{}])[0].get("billing_details", {}).get("email")),
            "status": "completed",
        })
    elif canonical_type == EventType.PAYMENT_FAILED:
        payload.update({
            "payment_id": obj.get("id"),
            "amount": (obj.get("amount", 0)) / 100.0,
            "currency": obj.get("currency", ""),
            "failure_reason": obj.get("last_payment_error", {}).get("message", ""),
            "status": "failed",
        })
    elif canonical_type == EventType.PAYMENT_REFUNDED:
        payload.update({
            "payment_id": obj.get("payment_intent"),
            "amount_refunded": (obj.get("amount_refunded", 0)) / 100.0,
            "currency": obj.get("currency", ""),
            "status": "refunded",
        })
    elif canonical_type in (EventType.SUBSCRIPTION_CREATED, EventType.SUBSCRIPTION_CANCELLED):
        payload.update({
            "subscription_id": obj.get("id"),
            "customer_id": obj.get("customer"),
            "status": obj.get("status"),
        })

    return InternalEvent(
        event_type=canonical_type,
        provider="stripe",
        schema_version=_SCHEMA_VERSION,
        tenant_id=tenant_id,
        payload=payload,
        occurred_at=datetime.fromtimestamp(event.get("created", time.time()), tz=timezone.utc),
        raw_event=event,
        idempotency_key=event.get("id", ""),
    )


def _normalize_twilio(event: dict, tenant_id: Optional[str]) -> InternalEvent:
    """Map a Twilio StatusCallback POST body to an InternalEvent."""
    msg_status = event.get("MessageStatus", event.get("SmsStatus", "")).lower()
    canonical_type = {
        "delivered": EventType.SMS_DELIVERED,
        "sent":      EventType.SMS_DELIVERED,
        "failed":    EventType.SMS_FAILED,
        "undelivered": EventType.SMS_FAILED,
    }.get(msg_status, EventType.UNKNOWN)

    payload = {
        "message_id": event.get("MessageSid"),
        "to": event.get("To"),
        "from": event.get("From"),
        "status": msg_status,
        "error_code": event.get("ErrorCode"),
        "error_message": event.get("ErrorMessage"),
        "provider_event_type": "message.status_callback",
    }

    return InternalEvent(
        event_type=canonical_type,
        provider="twilio",
        schema_version=_SCHEMA_VERSION,
        tenant_id=tenant_id,
        payload=payload,
        occurred_at=datetime.now(tz=timezone.utc),
        raw_event=event,
        idempotency_key=event.get("MessageSid", ""),
    )


def _normalize_calendly(event: dict, tenant_id: Optional[str]) -> InternalEvent:
    """Map a Calendly webhook payload to an InternalEvent."""
    event_type = event.get("event", "")
    payload_data = event.get("payload", {})

    type_map = {
        "invitee.created":   EventType.MEETING_SCHEDULED,
        "invitee.canceled":  EventType.MEETING_CANCELLED,
    }
    canonical_type = type_map.get(event_type, EventType.UNKNOWN)

    invitee = payload_data.get("invitee", {}) or payload_data
    scheduled_event = payload_data.get("scheduled_event", {}) or {}

    payload: dict[str, Any] = {
        "provider_event_type": event_type,
        "meeting_id": scheduled_event.get("uri", "").rsplit("/", 1)[-1],
        "attendee_name": invitee.get("name"),
        "attendee_email": invitee.get("email"),
        "start_datetime": scheduled_event.get("start_time"),
        "end_datetime": scheduled_event.get("end_time"),
        "cancel_reason": payload_data.get("cancel_url") if canonical_type == EventType.MEETING_CANCELLED else None,
    }

    created_at_str = event.get("created_at", "")
    try:
        occurred = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        occurred = datetime.now(tz=timezone.utc)

    return InternalEvent(
        event_type=canonical_type,
        provider="calendly",
        schema_version=_SCHEMA_VERSION,
        tenant_id=tenant_id,
        payload=payload,
        occurred_at=occurred,
        raw_event=event,
        idempotency_key=event.get("created_at", "") + invitee.get("email", ""),
    )


# ---------------------------------------------------------------------------
# Public normalize() entry point
# ---------------------------------------------------------------------------

_NORMALIZERS = {
    "stripe":   _normalize_stripe,
    "twilio":   _normalize_twilio,
    "calendly": _normalize_calendly,
}


def normalize(
    provider: str,
    raw_event: dict,
    tenant_id: Optional[str] = None,
) -> InternalEvent:
    """Normalize a raw provider webhook payload into an InternalEvent.

    Parameters
    ----------
    provider:  Provider name, e.g. "stripe"
    raw_event: Parsed JSON body from the webhook request
    tenant_id: Resolved tenant — None if not determinable from the payload
    """
    normalizer = _NORMALIZERS.get(provider)
    if normalizer is None:
        logger.warning("webhook_normalizer_not_found", provider=provider)
        return InternalEvent(
            event_type=EventType.UNKNOWN,
            provider=provider,
            schema_version=_SCHEMA_VERSION,
            tenant_id=tenant_id,
            payload={"provider_event": raw_event.get("type") or raw_event.get("event", "unknown")},
            occurred_at=datetime.now(tz=timezone.utc),
            raw_event=raw_event,
            idempotency_key=str(raw_event.get("id") or time.time()),
        )

    event = normalizer(raw_event, tenant_id)
    logger.info(
        "webhook_normalized",
        provider=provider,
        event_type=event.event_type,
        idempotency_key=event.idempotency_key,
        tenant_id=tenant_id,
    )
    return event
