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
import re
import secrets
from datetime import datetime, timezone
from typing import Optional

import structlog
from croniter import croniter
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.workflow import Workflow, WorkflowExecution, ExecutionStatus

logger = structlog.get_logger(__name__)

_CRON_POLL_INTERVAL = 60       # seconds between cron checks
_EVENT_CHANNEL      = "ascenai:events"   # Redis pub/sub channel
_RESUME_TOKEN_TTL   = 86_400   # 24 hours default resumption token TTL (seconds)
_RESUME_KEY_PREFIX  = "wf_resume:"
_CRON_KEY_PREFIX    = "wf_cron:"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _generate_resumption_token() -> str:
    return f"r-{secrets.token_urlsafe(6)}"


# ---------------------------------------------------------------------------
# Public helpers — used by workflow_engine.py SEND_SMS and external handlers
# ---------------------------------------------------------------------------

async def store_resumption_token(
    redis,
    token: str,
    execution_id: str,
    ttl_seconds: int = _RESUME_TOKEN_TTL,
) -> None:
    """Store token → execution_id mapping in Redis with TTL."""
    await redis.setex(f"{_RESUME_KEY_PREFIX}{token}", ttl_seconds, execution_id)


async def resolve_resumption_token(redis, token: str) -> Optional[str]:
    """Return execution_id for a token, or None if expired/unknown."""
    val = await redis.get(f"{_RESUME_KEY_PREFIX}{token}")
    return val.decode() if val else None


async def store_phone_execution(
    redis,
    phone: str,
    execution_id: str,
    ttl_seconds: int = _RESUME_TOKEN_TTL,
) -> None:
    """Secondary lookup: phone → most-recent AWAITING_EVENT execution_id."""
    key = f"wf_phone:{phone.strip().replace(' ', '')}"
    await redis.setex(key, ttl_seconds, execution_id)


async def resolve_phone_execution(redis, phone: str) -> Optional[str]:
    key = f"wf_phone:{phone.strip().replace(' ', '')}"
    val = await redis.get(key)
    return val.decode() if val else None


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

    async def start(self) -> None:
        self._running = True
        self._tasks = [
            asyncio.create_task(self._cron_loop()),
            asyncio.create_task(self._event_loop()),
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
        last_run = float(last_run_bytes.decode()) if last_run_bytes else 0.0

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
                pubsub = self.redis.pubsub()
                await pubsub.subscribe(_EVENT_CHANNEL)
                logger.info("workflow_event_subscriber_ready", channel=_EVENT_CHANNEL)

                async for message in pubsub.listen():
                    if not self._running:
                        break
                    if message["type"] != "message":
                        continue
                    try:
                        event = json.loads(message["data"])
                        await self._handle_event(event)
                    except Exception as exc:
                        logger.error("event_handler_error", error=str(exc))

            except Exception as exc:
                logger.error("event_loop_error", error=str(exc))
                await asyncio.sleep(5)  # back-off before reconnect

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
        """Route an inbound SMS reply to a waiting workflow execution.

        Called by the mcp-server Twilio webhook handler.
        Returns True if a workflow was resumed, False if no match found.
        """
        # Try resumption token first (token embedded in original SMS text)
        token_match = re.search(r"\br-[A-Za-z0-9_-]{6,10}\b", message_body)
        execution_id_str: Optional[str] = None

        if token_match:
            token = token_match.group(0)
            execution_id_str = await resolve_resumption_token(self.redis, token)

        # Fallback: phone → execution lookup
        if not execution_id_str:
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
                await engine.advance(
                    execution_id=execution_id,
                    user_input=message_body,
                    event_payload={"sms_reply": message_body, "from_phone": from_phone},
                )
                await db.commit()
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
        import uuid as _uuid
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

                # Generate resumption token if execution may await SMS reply
                token = _generate_resumption_token()
                execution.resumption_token = token
                await db.flush()

                # Store Redis lookups
                await store_resumption_token(self.redis, token, str(execution.id))
                if initial_context.get("customer_phone"):
                    await store_phone_execution(
                        self.redis,
                        initial_context["customer_phone"],
                        str(execution.id),
                    )

                # Update last_triggered_at on the workflow
                wf.last_triggered_at = _utcnow()

                # Advance one step
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
