"""Internal event bus — publishes InternalEvents to Redis Pub/Sub channels.

Architecture:
  Webhook receiver → normalizer → bus.publish() → Redis channel
                                                   ↓
                                    AI orchestrator subscriber
                                    (triggers workflow execution)

Channel naming:
  events:{tenant_id}:{event_type}   — tenant-scoped channel (most common)
  events:broadcast:{event_type}     — platform-wide (no tenant context)

Consumers (e.g. the orchestrator) subscribe to tenant channels to trigger
AI workflow actions (e.g. "send follow-up email when payment completes").

Deduplication:
  Each event carries an idempotency_key.  The bus checks a Redis key
  events:seen:{idempotency_key} (TTL 24h) before publishing, dropping
  re-delivered duplicates.
"""
from __future__ import annotations

import json
from typing import Optional

import structlog

from app.integrations.webhooks.normalizer import InternalEvent

logger = structlog.get_logger(__name__)

_DEDUP_TTL = 86_400   # 24 hours


class EventBus:
    """Thin Redis Pub/Sub publisher for InternalEvents."""

    def __init__(self, redis) -> None:
        self._redis = redis

    async def publish(self, event: InternalEvent) -> bool:
        """Publish an event onto the appropriate Redis channel.

        Returns True if published, False if deduplicated (already seen).
        """
        if self._redis is None:
            logger.warning("event_bus_redis_unavailable", event_type=event.event_type)
            return False

        # Deduplication check — prevents replayed webhooks from re-triggering
        if event.idempotency_key:
            dedup_key = f"events:seen:{event.idempotency_key}"
            already_seen = await self._redis.set(dedup_key, "1", nx=True, ex=_DEDUP_TTL)
            if not already_seen:
                logger.info(
                    "webhook_deduplicated",
                    idempotency_key=event.idempotency_key,
                    event_type=event.event_type,
                )
                return False

        channel = self._channel(event)
        message = json.dumps(event.to_dict(), default=str)

        await self._redis.publish(channel, message)
        logger.info(
            "event_published",
            channel=channel,
            event_type=event.event_type,
            provider=event.provider,
            tenant_id=event.tenant_id,
        )
        return True

    async def publish_many(self, events: list[InternalEvent]) -> int:
        """Publish a batch of events. Returns count of events actually published."""
        count = 0
        for event in events:
            if await self.publish(event):
                count += 1
        return count

    @staticmethod
    def _channel(event: InternalEvent) -> str:
        if event.tenant_id:
            return f"events:{event.tenant_id}:{event.event_type}"
        return f"events:broadcast:{event.event_type}"

    @classmethod
    def channel_pattern(cls, tenant_id: str) -> str:
        """Pattern string for PSUBSCRIBE to receive all events for a tenant."""
        return f"events:{tenant_id}:*"


def get_event_bus(redis) -> EventBus:
    """Factory — pass the app.state.redis client."""
    return EventBus(redis)
