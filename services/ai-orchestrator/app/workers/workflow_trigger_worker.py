"""WorkflowTriggerWorker — fires automation workflows from three sources:

1. CRON — polls every 60s for workflows whose next_run is due.
2. EVENT — subscribes to the internal Redis pub/sub bus; when a matching
   event fires (e.g. "payment.completed") it starts matching workflows.
3. SMS REPLY — when an inbound SMS arrives, look up the execution by
   resumption_token (or phone fallback) and advance it with the reply text.

Design
------
* Cron state is tracked in Redis: "wf_cron:{workflow_id}:last_run" (epoch).
* Event subscription runs as a long-lived Redis pub/sub consumer.
* Resumption tokens are stored in Redis with a TTL matching the workflow's
  AWAITING_EVENT expiry: "wf_resume:{token}" → execution_id.
* All execution creation/advance calls go through WorkflowEngine which owns
  the DB session — this worker never writes to the DB directly.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Optional

import structlog
from croniter import croniter
from sqlalchemy import select

from app.core.leadership import RedisLeaderLease
from app.core.database import AsyncSessionLocal
from app.models.workflow import Workflow, WorkflowExecution, ExecutionStatus

logger = structlog.get_logger(__name__)

_CRON_POLL_INTERVAL = 60       # seconds between cron checks
_EVENT_CHANNEL      = "ascenai:events"   # Redis pub/sub channel
_PHONE_KEY_TTL      = 86_400   # 24 hours — how long phone→execution mapping lives
_CRON_KEY_PREFIX    = "wf_cron:"
_PHONE_KEY_PREFIX   = "wf_phone:"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalise_phone(phone: str) -> str:
    """Strip spaces/dashes so +1-416-555-0123 and +14165550123 both match."""
    return phone.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")


# ---------------------------------------------------------------------------
# Public helpers — called by SEND_SMS node handler and inbound SMS webhook
# ---------------------------------------------------------------------------

async def store_phone_execution(
    redis,
    phone: str,
    execution_id: str,
    ttl_seconds: int = _PHONE_KEY_TTL,
) -> None:
    """Map the customer's phone number → execution_id in Redis with TTL.

    Called when a SEND_SMS node sets await_reply=True. The phone number IS
    the identity — no token required.
    """
    key = f"{_PHONE_KEY_PREFIX}{_normalise_phone(phone)}"
    await redis.setex(key, ttl_seconds, execution_id)


async def resolve_phone_execution(redis, phone: str) -> Optional[str]:
    """Return execution_id for this phone, or None if no waiting execution."""
    key = f"{_PHONE_KEY_PREFIX}{_normalise_phone(phone)}"
    val = await redis.get(key)
    return val.decode() if val else None


async def clear_phone_execution(redis, phone: str) -> None:
    """Remove the mapping once the execution is resumed or expired."""
    key = f"{_PHONE_KEY_PREFIX}{_normalise_phone(phone)}"
    await redis.delete(key)


# ---------------------------------------------------------------------------
# Worker class
# ---------------------------------------------------------------------------

class WorkflowTriggerWorker:
    """Background worker: cron triggers + event subscriptions + SMS resume."""

    def __init__(self, redis, interval_seconds: int = _CRON_POLL_INTERVAL) -> None:
        self.redis = redis
        self.interval = interval_seconds
        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._lease = RedisLeaderLease(redis, "ai-orchestrator:workflow-trigger")

    async def start(self) -> None:
        self._running = True
        self._tasks = [
            asyncio.create_task(self._cron_loop()),
            asyncio.create_task(self._event_loop()),
            asyncio.create_task(self._expiry_sweep_loop()),
        ]
        logger.info("workflow_trigger_worker_started")

    def stop(self) -> None:
        self._running = False
        for t in self._tasks:
            t.cancel()
        logger.info("workflow_trigger_worker_stopped")

    # ------------------------------------------------------------------
    # 1. CRON loop
    # ------------------------------------------------------------------

    async def _cron_loop(self) -> None:
        while self._running:
            try:
                if not await self._lease.acquire_or_renew():
                    await asyncio.sleep(self.interval)
                    continue
                await self._run_due_cron_workflows()
            except Exception as exc:
                logger.error("cron_loop_error", error=str(exc))
            await asyncio.sleep(self.interval)

    async def _run_due_cron_workflows(self) -> None:
        """Find all active cron workflows and fire any that are overdue."""
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Workflow).where(
                    Workflow.trigger_type == "cron",
                    Workflow.is_active.is_(True),
                )
            )
            workflows = result.scalars().all()

        for wf in workflows:
            try:
                await self._maybe_fire_cron(wf)
            except Exception as exc:
                logger.error(
                    "cron_fire_error",
                    workflow_id=str(wf.id),
                    error=str(exc),
                )

    async def _maybe_fire_cron(self, wf: Workflow) -> None:
        schedule  = wf.trigger_config.get("schedule", "")
        timezone_ = wf.trigger_config.get("timezone", "UTC")
        if not schedule:
            return

        now_epoch = _utcnow().timestamp()
        last_run_key = f"{_CRON_KEY_PREFIX}{wf.id}:last_run"

        last_run_bytes = await self.redis.get(last_run_key)
        # Prevent "cron fast-forward explosion": if cache is erased, 
        # do not start from 1970 (0.0). Start from exactly right now.
        last_run = float(last_run_bytes.decode()) if last_run_bytes else now_epoch

        cron = croniter(schedule, last_run)
        next_run = cron.get_next(float)

        if next_run <= now_epoch:
            logger.info("cron_workflow_firing", workflow_id=str(wf.id), schedule=schedule)
            await self._start_workflow_execution(
                workflow_id=wf.id,
                tenant_id=wf.tenant_id,
                agent_id=wf.agent_id,
                trigger_source="cron",
                initial_context={"_trigger": "cron", "_scheduled_at": _utcnow().isoformat()},
            )
            # Mark this cron slot consumed
            await self.redis.set(last_run_key, str(next_run))

    # ------------------------------------------------------------------
    # 2. EVENT loop — Redis pub/sub
    # ------------------------------------------------------------------

    async def _event_loop(self) -> None:
        """Subscribe to the internal event bus and route to matching workflows."""
        while self._running:
            try:
                if not await self._lease.acquire_or_renew():
                    await asyncio.sleep(5)
                    continue
                pubsub = self.redis.pubsub()
                await pubsub.subscribe(_EVENT_CHANNEL)
                logger.info("workflow_event_subscriber_ready", channel=_EVENT_CHANNEL)

                while self._running:
                    if not await self._lease.acquire_or_renew():
                        break
                    message = await pubsub.get_message(ignore_subscribe_messages=False, timeout=1.0)
                    if message is None:
                        continue
                    if not self._running:
                        break
                    if message["type"] != "message":
                        continue
                    try:
                        event = json.loads(message["data"])
                        await self._handle_event(event)
                    except Exception as exc:
                        logger.error("event_handler_error", error=str(exc))
                await pubsub.unsubscribe(_EVENT_CHANNEL)
                await pubsub.aclose()

            except Exception as exc:
                logger.error("event_loop_error", error=str(exc))
                await asyncio.sleep(5)  # back-off before reconnect

    async def _expiry_sweep_loop(self) -> None:
        """Sweep for expired AWAITING_EVENT executions every 60 seconds."""
        while self._running:
            try:
                if not await self._lease.acquire_or_renew():
                    await asyncio.sleep(self.interval)
                    continue
                await self._sweep_expired_executions()
            except Exception as exc:
                logger.error("expiry_sweep_loop_error", error=str(exc))
            await asyncio.sleep(self.interval)

    async def _sweep_expired_executions(self) -> None:
        """Find and mark AWAITING_EVENT executions as EXPIRED if past expiry_time."""
        now = _utcnow()
        
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(WorkflowExecution).where(
                    WorkflowExecution.status == ExecutionStatus.AWAITING_EVENT,
                    WorkflowExecution.expiry_time <= now,
                )
            )
            expired_executions = result.scalars().all()
            
            for execution in expired_executions:
                logger.info("workflow_execution_expired", execution_id=str(execution.id))
                execution.status = ExecutionStatus.EXPIRED
                execution.updated_at = now
                
                # Clear any phone mappings for this execution
                if execution.customer_phone:
                    await clear_phone_execution(self.redis, execution.customer_phone)
                
                await db.commit()
                
                # Record event
                from app.services.workflow_engine import WorkflowEngine
                engine = WorkflowEngine(db=db)
                await engine._record_event(
                    execution=execution,
                    event_type="EXECUTION_EXPIRED",
                    payload={"expiry_time": execution.expiry_time.isoformat()},
                )

    async def _handle_event(self, event: dict) -> None:
        """Match inbound event to subscribed workflows and fire them."""
        event_name    = event.get("event_type", event.get("type", ""))
        tenant_id_str = event.get("tenant_id", "")
        payload       = event.get("payload", event)

        if not event_name or not tenant_id_str:
            return

        import uuid as _uuid
        try:
            tenant_id = _uuid.UUID(tenant_id_str)
        except ValueError:
            return

        # Load all event-triggered workflows for this tenant
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Workflow).where(
                    Workflow.trigger_type == "event",
                    Workflow.is_active.is_(True),
                    Workflow.tenant_id == tenant_id,
                )
            )
            workflows = result.scalars().all()

        for wf in workflows:
            subscribed_event = wf.trigger_config.get("event", "")
            if subscribed_event != event_name:
                continue

            # Optional JSON filter: all filter keys must match payload
            event_filter = wf.trigger_config.get("filter", {})
            if event_filter:
                if not all(payload.get(k) == v for k, v in event_filter.items()):
                    continue

            logger.info(
                "event_workflow_firing",
                workflow_id=str(wf.id),
                event=event_name,
            )
            await self._start_workflow_execution(
                workflow_id=wf.id,
                tenant_id=wf.tenant_id,
                agent_id=wf.agent_id,
                trigger_source="event",
                initial_context={**payload, "_trigger": "event", "_event_type": event_name},
            )

    # ------------------------------------------------------------------
    # 3. SMS reply resume
    # ------------------------------------------------------------------

    async def handle_sms_reply(
        self,
        from_phone: str,
        message_body: str,
        tenant_id: str,
    ) -> bool:
        """Route an inbound SMS reply to the waiting workflow execution for this phone.

        The phone number is the sole identity — no token involved.
        If the sender's phone is not mapped to any waiting execution, returns False
        so the mcp-server can fall back to normal conversational handling.
        """
        execution_id_str = await resolve_phone_execution(self.redis, from_phone)
        if not execution_id_str:
            return False

        import uuid as _uuid
        try:
            execution_id = _uuid.UUID(execution_id_str)
        except ValueError:
            return False

        logger.info(
            "sms_reply_resuming_workflow",
            execution_id=execution_id_str,
            from_phone=from_phone,
        )

        async with AsyncSessionLocal() as db:
            try:
                from app.services.workflow_engine import WorkflowEngine
                engine = WorkflowEngine(db=db)
                result = await engine.advance(
                    execution_id=execution_id,
                    user_input=message_body,
                    event_payload={"sms_reply": message_body, "from_phone": from_phone},
                )
                await db.commit()

                # Clear the phone mapping — execution has been resumed.
                # If the workflow sends another await_reply SMS it will re-register.
                await clear_phone_execution(self.redis, from_phone)
                return True
            except Exception as exc:
                await db.rollback()
                logger.error("sms_reply_resume_error", error=str(exc))
                return False

    # ------------------------------------------------------------------
    # Internal helper
    # ------------------------------------------------------------------

    async def _start_workflow_execution(
        self,
        workflow_id,
        tenant_id,
        agent_id,
        trigger_source: str,
        initial_context: dict,
    ) -> None:
        import secrets as _secrets

        async with AsyncSessionLocal() as db:
            try:
                from app.services.workflow_engine import WorkflowEngine
                from app.models.workflow import Workflow as _WF

                wf = await db.scalar(select(_WF).where(_WF.id == workflow_id))
                if not wf or not wf.is_active:
                    return

                engine = WorkflowEngine(db=db)
                session_id = f"{trigger_source}:{_secrets.token_hex(8)}"
                execution = await engine.create_execution(
                    workflow_id=workflow_id,
                    session_id=session_id,
                    tenant_id=tenant_id,
                    initial_context=initial_context,
                    customer_phone=initial_context.get("customer_phone", ""),
                )
                execution.trigger_source = trigger_source
                await db.flush()

                # Register phone → execution mapping for SMS reply routing.
                # Phone number is the sole identity — no token needed.
                if initial_context.get("customer_phone"):
                    await store_phone_execution(
                        self.redis,
                        initial_context["customer_phone"],
                        str(execution.id),
                    )

                wf.last_triggered_at = _utcnow()

                await engine.advance(execution_id=execution.id)
                await db.commit()

                logger.info(
                    "workflow_execution_started",
                    workflow_id=str(workflow_id),
                    execution_id=str(execution.id),
                    trigger_source=trigger_source,
                )
            except Exception as exc:
                await db.rollback()
                logger.error(
                    "workflow_execution_start_error",
                    workflow_id=str(workflow_id),
                    trigger_source=trigger_source,
                    error=str(exc),
                )
