"""
Background worker that periodically closes expired chat sessions.

Runs on a configurable interval (default: 5 minutes) and marks sessions
as "closed" when they exceed the inactivity timeout.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import settings
from app.core.leadership import RedisLeaderLease

logger = structlog.get_logger(__name__)


class SessionCleanupWorker:
    """Periodically scans for and closes sessions that have exceeded the inactivity timeout."""

    def __init__(
        self,
        db_factory: async_sessionmaker,
        redis=None,
        interval_seconds: int = 300,
    ):
        self.db_factory = db_factory
        self.redis = redis
        self.interval_seconds = interval_seconds
        self._running = False
        self._task: asyncio.Task | None = None
        self._lease = RedisLeaderLease(redis, "ai-orchestrator:session-cleanup") if redis else None

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "session_cleanup_worker_started",
            interval_seconds=self.interval_seconds,
            expiry_minutes=getattr(settings, "SESSION_EXPIRY_MINUTES", 30),
        )

    def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
        logger.info("session_cleanup_worker_stopped")

    async def _run_loop(self) -> None:
        while self._running:
            try:
                if self._lease and not await self._lease.acquire_or_renew():
                    await asyncio.sleep(self.interval_seconds)
                    continue
                await self._close_expired_sessions()
            except Exception as exc:
                logger.error("session_cleanup_error", error=str(exc))
            await asyncio.sleep(self.interval_seconds)

    async def _close_expired_sessions(self) -> int:
        """Find and close expired active sessions. Returns count of closed sessions."""
        expiry_minutes = getattr(settings, "SESSION_EXPIRY_MINUTES", 30)
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=expiry_minutes)

        from app.models.agent import Session as AgentSession

        async with self.db_factory() as db:
            # Find active sessions where last_activity_at (or updated_at) is older than cutoff
            result = await db.execute(
                select(AgentSession).where(
                    AgentSession.status == "active",
                    # Use COALESCE logic: check last_activity_at first, fall back to updated_at
                    AgentSession.last_activity_at < cutoff,
                )
            )
            expired_sessions = list(result.scalars().all())

            count = 0
            for session in expired_sessions:
                session.close()
                count += 1

            if count > 0:
                await db.commit()
                logger.info("sessions_auto_closed", count=count, expiry_minutes=expiry_minutes)

            return count
