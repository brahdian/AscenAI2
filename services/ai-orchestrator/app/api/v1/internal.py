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
from fastapi import APIRouter, Depends, HTTPException, Header, Request
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
    from shared.orchestration.workflow_engine import WorkflowEngine, _SIGNAL_KEY_PREFIX

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


# ---------------------------------------------------------------------------
# Voice session → CRM auto-logging
# ---------------------------------------------------------------------------


class VoiceFinalizeRequest(BaseModel):
    tenant_id: str
    agent_id: str
    session_id: str
    caller_phone: Optional[str] = None
    duration_seconds: Optional[int] = None


class VoiceFinalizeResponse(BaseModel):
    logged: bool
    person_id: Optional[str] = None
    note_id: Optional[str] = None
    skipped_reason: Optional[str] = None


def _build_call_summary(messages: list, duration_seconds: Optional[int]) -> str:
    """Build a compact call summary from the message history.

    Truncates long messages and caps the overall body so we don't push pages
    of transcript into the CRM. The full transcript stays in our session DB.
    """
    if not messages:
        return "Voice call ended with no recorded transcript."

    lines: list[str] = []
    if duration_seconds:
        lines.append(f"Duration: {duration_seconds // 60}m {duration_seconds % 60}s")
    lines.append(f"Turns: {len(messages)}")
    lines.append("")

    tail = messages[-12:]
    for msg in tail:
        role = (getattr(msg, "role", None) or "").lower()
        speaker = "Caller" if role == "user" else "Agent" if role == "assistant" else role.capitalize()
        text = (getattr(msg, "content", None) or "").strip().replace("\n", " ")
        if len(text) > 240:
            text = text[:237] + "..."
        if text:
            lines.append(f"{speaker}: {text}")

    body = "\n".join(lines)
    return body[:4000]


@router.post("/voice/finalize", response_model=VoiceFinalizeResponse)
async def finalize_voice_session(
    body: VoiceFinalizeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_internal_key),
) -> VoiceFinalizeResponse:
    """Auto-log a finished voice call into Twenty CRM as a Note.

    All steps are best-effort. Any failure returns ``logged=false`` with a reason
    rather than raising — voice-pipeline calls this fire-and-forget after hangup.
    """
    from app.models.agent import Agent

    try:
        tenant_uuid = uuid.UUID(body.tenant_id)
        agent_uuid = uuid.UUID(body.agent_id)
    except ValueError:
        return VoiceFinalizeResponse(logged=False, skipped_reason="invalid_id_format")

    agent_row = (
        await db.execute(select(Agent).where(Agent.id == agent_uuid, Agent.tenant_id == tenant_uuid))
    ).scalar_one_or_none()
    if agent_row is None:
        return VoiceFinalizeResponse(logged=False, skipped_reason="agent_not_found")

    if not agent_row.crm_workspace_id:
        return VoiceFinalizeResponse(logged=False, skipped_reason="no_crm_workspace")

    if not (agent_row.agent_config or {}).get("auto_log_to_crm"):
        return VoiceFinalizeResponse(logged=False, skipped_reason="auto_log_disabled")

    msg_rows = (
        await db.execute(
            select(Message)
            .where(Message.session_id == body.session_id, Message.tenant_id == tenant_uuid)
            .order_by(Message.created_at)
        )
    ).scalars().all()

    summary = _build_call_summary(list(msg_rows), body.duration_seconds)

    mcp = getattr(request.app.state, "mcp_client", None)
    if mcp is None:
        return VoiceFinalizeResponse(logged=False, skipped_reason="mcp_unavailable")

    crm_workspace_id = str(agent_row.crm_workspace_id)
    person_id: Optional[str] = None

    if body.caller_phone:
        try:
            lookup = await mcp.execute_tool(
                tenant_id=body.tenant_id,
                tool_name="crm_lookup",
                parameters={"phone": body.caller_phone},
                session_id=body.session_id,
                crm_workspace_id=crm_workspace_id,
            )
            result = (lookup or {}).get("result") or {}
            if result.get("found"):
                person_id = (result.get("customer") or {}).get("id")
            elif "error" not in result:
                create = await mcp.execute_tool(
                    tenant_id=body.tenant_id,
                    tool_name="crm_create_person",
                    parameters={"phone": body.caller_phone},
                    session_id=body.session_id,
                    crm_workspace_id=crm_workspace_id,
                )
                person_id = ((create or {}).get("result") or {}).get("id")
        except Exception as exc:
            logger.warning("voice_finalize_lookup_failed", session_id=body.session_id, error=str(exc))

    note_params: dict = {
        "title": f"Voice call · {body.session_id[:8]}",
        "body": summary,
    }
    if person_id:
        note_params["person_id"] = person_id

    try:
        note_resp = await mcp.execute_tool(
            tenant_id=body.tenant_id,
            tool_name="crm_create_note",
            parameters=note_params,
            session_id=body.session_id,
            crm_workspace_id=crm_workspace_id,
        )
        note_result = (note_resp or {}).get("result") or {}
        note_id = note_result.get("id")
    except Exception as exc:
        logger.warning("voice_finalize_note_failed", session_id=body.session_id, error=str(exc))
        return VoiceFinalizeResponse(logged=False, person_id=person_id, skipped_reason="note_failed")

    logger.info(
        "voice_session_logged_to_crm",
        session_id=body.session_id,
        person_id=person_id,
        note_id=note_id,
    )
    return VoiceFinalizeResponse(logged=bool(note_id), person_id=person_id, note_id=note_id)
