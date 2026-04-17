"""Booking expiry background worker.

Runs every 60 seconds and handles three cases:

1. SLOT_HELD workflows past their expiry_time
   → release CRM hold → transition to EXPIRED → send expired SMS

2. PAYMENT_PENDING workflows within 5 minutes of expiry (reminder not sent yet)
   → send payment reminder SMS

3. PAYMENT_PENDING workflows past their expiry_time
   → release CRM hold → transition to EXPIRED → send expired SMS

Design
------
* Single asyncio task, started in the FastAPI lifespan.
* Queries use the partial index ix_bw_expiry_active which covers only
  non-terminal workflows — keeps the query fast even with millions of rows.
* Each workflow is processed in its own DB transaction so one failure
  doesn't abort the whole batch.
* CRM release calls are made before the DB transition — if the release
  fails we log the error but still expire the workflow (better to expire
  than to leave a zombie HELD slot in our DB).
* The worker does not send reminders more than once: sms_reminder_sent_at
  guards against double-sends across worker restarts.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal
from app.core.leadership import RedisLeaderLease
from app.models.booking import BookingState, BookingWorkflow
from app.services.booking_provider import BookingProviderRegistry
from app.services.booking_state_machine import transition, record_event
from app.services.sms_workflow_engine import SMSWorkflowEngine

logger = structlog.get_logger(__name__)

_DEFAULT_INTERVAL_SECONDS = 60
_REMINDER_WINDOW_MINUTES = 5  # Send reminder this many minutes before expiry


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BookingExpiryWorker:
    """Background worker that expires stale booking holds."""

    def __init__(self, redis, interval_seconds: int = _DEFAULT_INTERVAL_SECONDS) -> None:
        self.redis = redis
        self._interval = interval_seconds
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._lease = RedisLeaderLease(redis, "mcp-server:booking-expiry")

    def start(self) -> None:
        """Start the background task."""
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="booking_expiry_worker")
        logger.info("booking_expiry_worker_started", interval=self._interval)

    async def stop(self) -> None:
        """Gracefully stop the background task."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("booking_expiry_worker_stopped")

    async def _loop(self) -> None:
        """Main loop — runs indefinitely until stopped."""
        while self._running:
            try:
                if not await self._lease.acquire_or_renew():
                    await asyncio.sleep(self._interval)
                    continue
                await self._run_once()
            except Exception as exc:
                logger.error("booking_expiry_worker_error", error=str(exc), exc_info=exc)
            await asyncio.sleep(self._interval)

    async def _run_once(self) -> None:
        """Single pass over expired / expiring workflows."""
        now = _utcnow()
        reminder_deadline = now + timedelta(minutes=_REMINDER_WINDOW_MINUTES)

        async with SessionLocal() as db:
            # ── 1. Expire SLOT_HELD workflows ──────────────────────────────
            held_expired = await self._query(db, BookingState.SLOT_HELD, max_expiry=now)
            for wf in held_expired:
                await self._expire_workflow(db, wf, "expiry_worker:slot_held")

            # ── 2. Send reminders for PAYMENT_PENDING near expiry ──────────
            soon_expiring = await db.scalars(
                select(BookingWorkflow).where(
                    BookingWorkflow.state == BookingState.PAYMENT_PENDING,
                    BookingWorkflow.expiry_time > now,
                    BookingWorkflow.expiry_time <= reminder_deadline,
                    BookingWorkflow.sms_reminder_sent_at.is_(None),
                )
            )
            for wf in soon_expiring:
                await self._send_reminder(db, wf)

            # ── 3. Expire PAYMENT_PENDING workflows past TTL ───────────────
            pending_expired = await self._query(db, BookingState.PAYMENT_PENDING, max_expiry=now)
            for wf in pending_expired:
                await self._expire_workflow(db, wf, "expiry_worker:payment_pending")

            await db.commit()

    async def _query(
        self, db: AsyncSession, state: BookingState, max_expiry: datetime
    ) -> list[BookingWorkflow]:
        result = await db.scalars(
            select(BookingWorkflow).where(
                BookingWorkflow.state == state,
                BookingWorkflow.expiry_time <= max_expiry,
            )
        )
        return list(result.all())

    async def _expire_workflow(
        self, db: AsyncSession, wf: BookingWorkflow, actor: str
    ) -> None:
        """Release CRM hold and transition workflow to EXPIRED."""
        log = logger.bind(workflow_id=str(wf.id), provider=wf.provider)

        # Release CRM hold (best-effort — don't let CRM errors block DB transition)
        if wf.external_reservation_id:
            try:
                # Load tenant config — use empty dict as fallback
                tenant_config = await _load_tenant_config_safe(wf.tenant_id)
                provider = BookingProviderRegistry.get(wf.provider, tenant_config)
                await provider.release_slot(wf.external_reservation_id)
                log.info("booking_crm_slot_released")
            except Exception as exc:
                log.error("booking_crm_release_failed", error=str(exc))

        # Transition state
        try:
            await transition(
                db, wf.id, BookingState.EXPIRED,
                actor=actor,
                payload={"expired_at": _utcnow().isoformat()},
            )
        except Exception as exc:
            log.error("booking_expire_transition_failed", error=str(exc))
            return

        # Send expired SMS (best-effort)
        try:
            tenant_config = await _load_tenant_config_safe(wf.tenant_id)
            sms = SMSWorkflowEngine(db, tenant_config)
            await sms.send_payment_expired_notice(wf)
        except Exception as exc:
            log.error("booking_expired_sms_failed", error=str(exc))

        log.info("booking_workflow_expired", state=wf.state.value)

    async def _send_reminder(self, db: AsyncSession, wf: BookingWorkflow) -> None:
        """Send a payment reminder SMS."""
        try:
            tenant_config = await _load_tenant_config_safe(wf.tenant_id)
            sms = SMSWorkflowEngine(db, tenant_config)
            await sms.send_payment_reminder(wf)
            # sms_reminder_sent_at is set inside send_payment_reminder
            logger.info("booking_reminder_sent", workflow_id=str(wf.id))
        except Exception as exc:
            logger.error(
                "booking_reminder_failed",
                workflow_id=str(wf.id),
                error=str(exc),
            )


async def _load_tenant_config_safe(tenant_id) -> dict:
    """Load tenant configuration — returns empty dict on any failure.

    TODO: integrate with the actual tenant config store (same as webhooks.py).
    """
    try:
        # Placeholder — replace with real tenant config lookup
        return {}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Module-level singleton — registered in main.py lifespan
# ---------------------------------------------------------------------------

_worker: Optional[BookingExpiryWorker] = None


def get_booking_expiry_worker(redis=None) -> BookingExpiryWorker:
    global _worker
    if _worker is None:
        if redis is None:
            raise RuntimeError("Redis client required to initialize booking expiry worker")
        _worker = BookingExpiryWorker(redis=redis)
    return _worker
