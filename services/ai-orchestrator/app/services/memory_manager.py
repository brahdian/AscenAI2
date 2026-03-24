import json
from typing import Optional

import structlog
import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.config import settings

logger = structlog.get_logger(__name__)

SESSION_MEMORY_PREFIX = "session:memory:"
SESSION_SUMMARY_PREFIX = "session:summary:"
CUSTOMER_MEMORY_PREFIX = "customer:memory:"
MEMORY_TTL_SECONDS = 86400 * 7  # 7 days


class MemoryManager:
    """
    Manages short-term (Redis) and long-term (PostgreSQL) memory for sessions.

    Short-term memory: A sliding window of the last N messages per session,
    stored in a Redis list for fast retrieval.

    Long-term memory: Customer preferences and interaction history stored in
    PostgreSQL for cross-session context.
    """

    def __init__(self, redis_client: aioredis.Redis, db: AsyncSession):
        self.redis = redis_client
        self.db = db
        self.window_size = settings.MEMORY_WINDOW_SIZE

    def _session_key(self, session_id: str) -> str:
        return f"{SESSION_MEMORY_PREFIX}{session_id}"

    def _summary_key(self, session_id: str) -> str:
        return f"{SESSION_SUMMARY_PREFIX}{session_id}"

    def _customer_key(self, tenant_id: str, customer_id: str) -> str:
        return f"{CUSTOMER_MEMORY_PREFIX}{tenant_id}:{customer_id}"

    async def get_short_term_memory(self, session_id: str) -> list[dict]:
        """
        Retrieve the recent messages for a session from Redis.
        Returns a list of message dicts ordered oldest to newest.
        """
        key = self._session_key(session_id)
        try:
            raw_messages = await self.redis.lrange(key, 0, -1)
            messages = []
            for raw in raw_messages:
                try:
                    messages.append(json.loads(raw))
                except json.JSONDecodeError:
                    logger.warning("memory_decode_error", session_id=session_id, raw=raw)
            return messages
        except Exception as exc:
            logger.error("get_short_term_memory_error", session_id=session_id, error=str(exc))
            return []

    async def add_to_short_term_memory(self, session_id: str, message: dict):
        """
        Append a message to the Redis list for the session.
        Trims the list to the configured window size (MEMORY_WINDOW_SIZE).
        Refreshes the TTL on each write.
        """
        key = self._session_key(session_id)
        try:
            serialized = json.dumps(message, default=str)
            pipe = self.redis.pipeline()
            pipe.rpush(key, serialized)
            # Keep only the most recent window_size messages
            pipe.ltrim(key, -self.window_size, -1)
            pipe.expire(key, MEMORY_TTL_SECONDS)
            await pipe.execute()
        except Exception as exc:
            logger.error("add_to_short_term_memory_error", session_id=session_id, error=str(exc))

    async def get_session_summary(self, session_id: str) -> Optional[str]:
        """
        Retrieve a pre-computed summary of older conversation context from Redis.
        Returns None if no summary exists.
        """
        key = self._summary_key(session_id)
        try:
            summary = await self.redis.get(key)
            return summary
        except Exception as exc:
            logger.error("get_session_summary_error", session_id=session_id, error=str(exc))
            return None

    async def create_session_summary(
        self, session_id: str, messages: list[dict]
    ) -> str:
        """
        Use LLM-style compression to summarize older messages.
        Creates a condensed summary and stores it in Redis.

        For now, produces a structured text summary without calling the LLM
        (to avoid circular dependencies). In production, inject the LLM client.
        """
        if not messages:
            return ""

        lines = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, str) and content:
                lines.append(f"{role.capitalize()}: {content[:200]}")

        summary = "Earlier conversation summary:\n" + "\n".join(lines[:20])

        key = self._summary_key(session_id)
        try:
            await self.redis.set(key, summary, ex=MEMORY_TTL_SECONDS)
        except Exception as exc:
            logger.error("create_session_summary_error", session_id=session_id, error=str(exc))

        return summary

    async def get_long_term_customer_memory(
        self, tenant_id: str, customer_id: str
    ) -> dict:
        """
        Retrieve long-term customer preferences and history.
        First checks Redis cache, then falls back to PostgreSQL.
        """
        cache_key = self._customer_key(tenant_id, customer_id)
        try:
            cached = await self.redis.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception as exc:
            logger.warning("customer_memory_cache_error", error=str(exc))

        # Fall back to database query for customer history
        try:
            from app.models.agent import Message, Session as AgentSession
            from sqlalchemy import and_

            # Get recent sessions for this customer
            result = await self.db.execute(
                select(AgentSession)
                .where(
                    and_(
                        AgentSession.tenant_id == tenant_id,
                        AgentSession.customer_identifier == customer_id,
                        AgentSession.status.in_(["completed", "escalated"]),
                    )
                )
                .order_by(AgentSession.started_at.desc())
                .limit(5)
            )
            sessions = result.scalars().all()

            # Collect summary stats
            session_ids = [s.id for s in sessions]
            total_messages = 0
            recent_intents: list[str] = []

            if session_ids:
                msg_count_result = await self.db.execute(
                    select(func.count(Message.id)).where(
                        Message.session_id.in_(session_ids)
                    )
                )
                total_messages = msg_count_result.scalar() or 0

            customer_memory = {
                "customer_id": customer_id,
                "tenant_id": tenant_id,
                "total_sessions": len(sessions),
                "total_messages": total_messages,
                "last_session_at": sessions[0].started_at.isoformat() if sessions else None,
                "preferences": {},
                "recent_intents": recent_intents,
                "channels_used": list({s.channel for s in sessions}),
            }

            # Cache for 1 hour
            try:
                await self.redis.set(
                    cache_key, json.dumps(customer_memory, default=str), ex=3600
                )
            except Exception:
                pass

            return customer_memory

        except Exception as exc:
            logger.error(
                "get_long_term_customer_memory_error",
                tenant_id=tenant_id,
                customer_id=customer_id,
                error=str(exc),
            )
            return {
                "customer_id": customer_id,
                "tenant_id": tenant_id,
                "total_sessions": 0,
                "preferences": {},
            }

    async def update_customer_memory(
        self, tenant_id: str, customer_id: str, update: dict
    ):
        """
        Update the customer memory profile after a session ends.
        Merges the update dict into the existing profile and re-caches.
        """
        current = await self.get_long_term_customer_memory(tenant_id, customer_id)
        current.update(update)

        cache_key = self._customer_key(tenant_id, customer_id)
        try:
            await self.redis.set(
                cache_key, json.dumps(current, default=str), ex=3600
            )
        except Exception as exc:
            logger.error("update_customer_memory_error", error=str(exc))

    async def clear_session(self, session_id: str):
        """
        Remove all short-term memory for a session from Redis.
        Called when a session ends or is explicitly cleared.
        """
        keys = [
            self._session_key(session_id),
            self._summary_key(session_id),
        ]
        try:
            await self.redis.delete(*keys)
            logger.info("session_memory_cleared", session_id=session_id)
        except Exception as exc:
            logger.error("clear_session_error", session_id=session_id, error=str(exc))

    async def get_full_context(
        self, session_id: str, tenant_id: str, customer_id: Optional[str]
    ) -> dict:
        """
        Convenience method: fetch short-term memory, summary, and customer profile.
        Returns a unified context dict for the orchestrator.
        """
        short_term = await self.get_short_term_memory(session_id)
        summary = await self.get_session_summary(session_id)
        customer_memory: dict = {}

        if customer_id:
            customer_memory = await self.get_long_term_customer_memory(tenant_id, customer_id)

        return {
            "messages": short_term,
            "summary": summary,
            "customer_profile": customer_memory,
        }
