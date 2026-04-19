"""
Internal API endpoints — not exposed to end-users.

These endpoints are called service-to-service (e.g. api-gateway → ai-orchestrator)
and must not be reachable from the public internet.  Every request must present the
shared INTERNAL_API_KEY in the X-Internal-Key header; the InternalAuthMiddleware
already rejects requests that fail this check for non-public paths.

An explicit per-route guard (``_require_internal_key``) is added as defense-in-depth
so these endpoints remain protected even if middleware configuration changes.
"""
from __future__ import annotations

import hashlib
import hmac
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.core.config import settings
from app.core.database import get_db
from app.models.agent import Message, Session as AgentSession

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/internal")


def _require_internal_key(x_internal_key: Optional[str] = Header(default=None)) -> None:
    """
    Defense-in-depth guard: verify the shared INTERNAL_API_KEY is present and correct.

    The InternalAuthMiddleware already rejects bad keys at the middleware layer.
    This per-route check ensures the endpoint remains protected even if the
    middleware is bypassed (e.g. direct uvicorn access without nginx/middleware).
    """
    expected = getattr(settings, "INTERNAL_API_KEY", "")
    if not expected:
        # If no key is configured we still accept the request but log a warning.
        # This preserves backwards-compatibility for deployments that haven't yet
        # configured INTERNAL_API_KEY (e.g. local dev).
        logger.warning(
            "internal_key_not_configured",
            detail="Set INTERNAL_API_KEY to protect internal endpoints.",
        )
        return
    if not x_internal_key or not hmac.compare_digest(
        x_internal_key.encode(), expected.encode()
    ):
        raise HTTPException(status_code=401, detail="Invalid internal credentials.")


class ErasureRequest(BaseModel):
    tenant_id: str
    customer_identifier: str
    reason: str = ""


class ErasureResponse(BaseModel):
    sessions_anonymized: int
    messages_deleted: int


@router.post("/erasure", response_model=ErasureResponse)
async def erasure(
    body: ErasureRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_internal_key),
) -> ErasureResponse:
    """
    GDPR / PIPEDA right-to-erasure handler.

    1. Deletes all Message rows that belong to sessions owned by
       (tenant_id, customer_identifier).
    2. Anonymizes those Session rows: sets customer_identifier to
       a SHA-256 hash prefix and clears metadata, preserving analytics counts.
    """
    try:
        tenant_uuid = uuid.UUID(body.tenant_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid tenant_id format.")

    session_result = await db.execute(
        select(AgentSession.id).where(
            AgentSession.tenant_id == tenant_uuid,
            AgentSession.customer_identifier == body.customer_identifier,
        )
    )
    session_ids = [row[0] for row in session_result.all()]

    messages_deleted = 0
    if session_ids:
        del_result = await db.execute(
            delete(Message).where(
                Message.session_id.in_(session_ids),
                Message.tenant_id == tenant_uuid,
            )
        )
        messages_deleted = del_result.rowcount or 0

        _id_hash = hashlib.sha256(body.customer_identifier.encode()).hexdigest()[:16]
        anon_identifier = f"[ERASED:{_id_hash}]"

        await db.execute(
            update(AgentSession)
            .where(AgentSession.id.in_(session_ids))
            .values(customer_identifier=anon_identifier, metadata_={})
        )

    await db.commit()

    sessions_anonymized = len(session_ids)
    logger.info(
        "erasure_completed",
        tenant_id=body.tenant_id,
        sessions_anonymized=sessions_anonymized,
        messages_deleted=messages_deleted,
        reason=body.reason,
    )
    return ErasureResponse(
        sessions_anonymized=sessions_anonymized,
        messages_deleted=messages_deleted,
    )


# ---------------------------------------------------------------------------
# WAIT_FOR_SIGNAL delivery endpoint
# ---------------------------------------------------------------------------

class SignalRequest(BaseModel):
    """Payload delivered by an external system to resume a WAIT_FOR_SIGNAL node.

    Fields
    ------
    correlation_id : str — must match the correlation_value stored in Redis
                    (usually the session_id or a custom order/payment ID)
    payload        : dict — injected as event_payload into the workflow context
    """
    correlation_id: str
    payload: dict = {}


class SignalResponse(BaseModel):
    signal_name: str
    execution_id: Optional[str]
    resumed: bool
    message: str


@router.post("/workflows/signal/{signal_name}", response_model=SignalResponse)
async def deliver_signal(
    signal_name: str,
    body: SignalRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_internal_key),
) -> SignalResponse:
    """Deliver a named signal to a paused WAIT_FOR_SIGNAL execution.

    Flow
    ----
    1. Look up Redis key  wf:signal:{signal_name}:{correlation_id}  → execution_id
    2. Load the WorkflowExecution (confirm it exists and is AWAITING_EVENT)
    3. Merge signal payload into event_payload and call WorkflowEngine.advance()
    4. Return the advance result summary
    """
    from app.core.redis_client import get_redis
    from app.models.workflow import WorkflowExecution, ExecutionStatus
    from app.services.workflow_engine import WorkflowEngine, _SIGNAL_KEY_PREFIX

    redis = await get_redis()
    redis_key = f"{_SIGNAL_KEY_PREFIX}{signal_name}:{body.correlation_id}"

    raw_exec_id = None
    if redis:
        raw_exec_id = await redis.get(redis_key)

    if not raw_exec_id:
        logger.warning(
            "signal_execution_not_found",
            signal_name=signal_name,
            correlation_id=body.correlation_id,
        )
        return SignalResponse(
            signal_name=signal_name,
            execution_id=None,
            resumed=False,
            message=f"No paused execution found for signal '{signal_name}' / correlation '{body.correlation_id}'",
        )

    execution_id_str = raw_exec_id if isinstance(raw_exec_id, str) else raw_exec_id.decode()

    try:
        execution_id = uuid.UUID(execution_id_str)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Corrupt execution_id in Redis: {execution_id_str}")

    import asyncio
    
    # -------------------------------------------------------------------------
    # Race Condition Safety: The node writes to Redis and then suspends in DB.
    # If the webhook is incredibly fast, it might hit this API before the
    # parent workflow engine has finished committing the AWAITING_EVENT state
    # to the database. We poll up to 5 times (2.5s) to let the commit land.
    # -------------------------------------------------------------------------
    max_retries = 5
    execution = None
    
    for attempt in range(max_retries):
        # populate_existing=True forces SQLAlchemy to overwrite the Identity Map
        # with fresh data from the DB, otherwise we'd just read stale cache.
        execution = await db.scalar(
            select(WorkflowExecution)
            .where(WorkflowExecution.id == execution_id)
            .execution_options(populate_existing=True)
        )
        
        if not execution:
            return SignalResponse(
                signal_name=signal_name,
                execution_id=execution_id_str,
                resumed=False,
                message="Execution not found in database.",
            )

        if execution.status in (ExecutionStatus.AWAITING_EVENT, ExecutionStatus.AWAITING_INPUT):
            break  # Ready to resume

        if attempt < max_retries - 1:
            logger.debug(
                "signal_delivery_race_retry", 
                attempt=attempt+1, 
                current_status=execution.status.value
            )
            await asyncio.sleep(0.5)
            continue
            
        # If we exhausted retries and it's still not awaiting
        return SignalResponse(
            signal_name=signal_name,
            execution_id=execution_id_str,
            resumed=False,
            message=f"Execution is not paused (status={execution.status.value}). Signal ignored.",
        )

    # Derive the output_variable name from the stored signal_name on the execution
    # The engine will look for this key in context to know the signal arrived
    cfg_output_var = "signal_payload"  # default; overridden if node config specifies it

    # Merge signal payload into event_payload so WorkflowEngine.advance() picks it up
    event_payload = {**body.payload, cfg_output_var: body.payload}

    engine = WorkflowEngine(db=db, redis=redis)
    result = await engine.advance(
        execution_id=execution_id,
        event_payload=event_payload,
    )
    await db.commit()

    # Clean up Redis key after successful delivery
    if redis:
        await redis.delete(redis_key)

    logger.info(
        "signal_delivered",
        signal_name=signal_name,
        execution_id=execution_id_str,
        correlation_id=body.correlation_id,
        status=result.status.value,
    )

    return SignalResponse(
        signal_name=signal_name,
        execution_id=execution_id_str,
        resumed=True,
        message=f"Signal delivered. Execution status: {result.status.value}",
    )

