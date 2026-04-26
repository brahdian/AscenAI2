"""
IdempotencyService
==================
Production-grade idempotency guard for critical operations (billing webhooks,
agent slot activations).

Strategy (defence-in-depth):
  1. PRIMARY  — Redis SETNX with 7-day TTL (fast, in-memory).
  2. FALLBACK — DB upsert into `processed_events` table when Redis is down.

This prevents Stripe (3-day retry window) and any other external system from
double-processing events even during a full Redis outage.

Usage:
    svc = IdempotencyService(db=db, redis=request.app.state.redis)
    already_done = await svc.is_already_processed("stripe_event", event_id)
    if already_done:
        return {"received": True}
    # … process event …
    await svc.mark_processed("stripe_event", event_id)
"""
from __future__ import annotations

import hashlib
import struct
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# 7 days — covers Stripe's maximum retry window (3 days) with 2× safety margin
_DEFAULT_TTL_SECONDS: int = 7 * 24 * 3600


class IdempotencyService:
    """Thread-safe, Redis+DB backed idempotency guard."""

    def __init__(self, db: AsyncSession, redis=None):
        self.db = db
        self.redis = redis

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def check_and_acquire_lock(self, namespace: str, key: str, lock_ttl: int = 300) -> bool:
        """
        Check if an event is processed. If not, acquire a temporary lock to process it.
        Returns `True` if it's safe to process (lock acquired), `False` if already processing/processed.
        """
        redis_key = self._redis_key(namespace, key)

        # 1. Try to acquire lock in Redis
        if self.redis is not None:
            try:
                # SETNX prevents concurrent identical webhooks from executing simultaneously
                acquired = await self.redis.set(redis_key, "processing", nx=True, ex=lock_ttl)
                if not acquired:
                    logger.info("idempotency_locked_or_processed", namespace=namespace, key=key[:16] + "…")
                    return False
            except Exception as redis_err:
                logger.warning("idempotency_redis_lock_failed", error=str(redis_err), namespace=namespace)

        # 2. We acquired the lock (or Redis is down). Check DB fallback to ensure it wasn't
        # processed in the past and merely evicted from Redis.
        #
        # Phase 9: Database advisory lock (concurrency control for DB check)
        # Convert key to deterministic 64-bit int for Postgres
        key_hash = hashlib.sha256(f"{namespace}:{key}".encode()).digest()
        lock_id = struct.unpack("q", key_hash[:8])[0]
        try:
            lock_res = await self.db.execute(
                text("SELECT pg_try_advisory_xact_lock(:lock_id)"),
                {"lock_id": lock_id}
            )
            if not lock_res.scalar():
                logger.info("idempotency_db_lock_busy", namespace=namespace, key=key[:16] + "…")
                return False
        except Exception as lock_err:
            logger.warning("idempotency_advisory_lock_skipped", error=str(lock_err))

        try:
            row = await self.db.execute(
                text(
                    "SELECT 1 FROM processed_events "
                    "WHERE namespace = :ns AND event_key = :key"
                ),
                {"ns": namespace, "key": self._db_key(key)},
            )
            if row.first() is not None:
                logger.info("idempotency_db_hit", namespace=namespace, key=key[:16] + "…")
                # Back-fill Redis tombstone so future checks are fast
                if self.redis is not None:
                    try:
                        await self.redis.setex(redis_key, _DEFAULT_TTL_SECONDS, "1")
                    except Exception:
                        pass
                return False
        except Exception as db_err:
            logger.error("idempotency_db_check_failed", error=str(db_err), namespace=namespace)
            # Proceed if DB query fails, allowing the business logic to handle partial failures

        return True

    async def mark_processed(self, namespace: str, key: str) -> None:
        """Record that (namespace, key) has been successfully processed."""
        redis_key = self._redis_key(namespace, key)

        # 1. Write to Redis
        if self.redis is not None:
            try:
                await self.redis.setex(redis_key, _DEFAULT_TTL_SECONDS, "1")
            except Exception as redis_err:
                logger.warning(
                    "idempotency_redis_write_failed",
                    error=str(redis_err),
                    namespace=namespace,
                )

        # 2. Write to DB (primary durability store)
        try:
            await self.db.execute(
                text(
                    "INSERT INTO processed_events (id, namespace, event_key, processed_at) "
                    "VALUES (:id, :ns, :key, :now) "
                    "ON CONFLICT (namespace, event_key) DO NOTHING"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "ns": namespace,
                    "key": self._db_key(key),
                    "now": datetime.now(timezone.utc),
                },
            )
            # NOTE: caller must commit the outer transaction.
        except Exception as db_err:
            logger.error(
                "idempotency_db_write_failed",
                error=str(db_err),
                namespace=namespace,
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _redis_key(namespace: str, key: str) -> str:
        return f"idempotency:{namespace}:{key}"

    @staticmethod
    def _db_key(key: str) -> str:
        """Hash long keys to a fixed-length DB column value (SHA-256, hex)."""
        if len(key) <= 255:
            return key
        return hashlib.sha256(key.encode()).hexdigest()
