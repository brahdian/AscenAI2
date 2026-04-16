"""Internal event bus — Redis pub/sub for cross-workflow event triggers.

Usage
-----
From anywhere in ai-orchestrator:

    from app.services.event_bus import publish_event
    await publish_event(redis, "payment.completed", tenant_id=str(tenant_id), payload={...})

WorkflowTriggerWorker subscribes to the channel and fires any workflows whose
trigger_config.event matches the event_type.

Event schema
------------
{
  "event_type": "payment.completed",
  "tenant_id":  "uuid-string",
  "payload":    {...}          # arbitrary data becomes initial workflow context
}

Standard event names
--------------------
payment.completed         — Stripe/Square payment succeeded
payment.failed            — payment failed / expired
booking.confirmed         — appointment confirmed
booking.cancelled         — appointment cancelled
session.ended             — chat/call session closed
lead.created              — new lead captured
order.placed              — order placed
order.shipped             — order shipped
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

_CHANNEL = "ascenai:events"


async def publish_event(
    redis,
    event_type: str,
    tenant_id: str,
    payload: dict,
) -> None:
    """Publish a named event onto the internal bus.

    Fire-and-forget: errors are swallowed so callers never crash on bus failure.
    """
    try:
        message = json.dumps({
            "event_type": event_type,
            "tenant_id":  tenant_id,
            "payload":    payload,
            "published_at": datetime.now(timezone.utc).isoformat(),
        })
        await redis.publish(_CHANNEL, message)
    except Exception:
        pass  # Bus failure must never crash the caller
