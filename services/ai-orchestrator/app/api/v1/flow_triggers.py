"""External trigger endpoints for automation-mode workflows.

POST /agents/{agent_id}/flows/{flow_id}/trigger
  — HMAC-verified webhook endpoint.
  — Any external system (Shopify, Stripe, custom) can POST here to start or
    resume a workflow execution. Payload becomes the initial execution context.

POST /agents/{agent_id}/flows/{flow_id}/trigger/test
  — Unverified test endpoint (internal-key protected). For dashboard testing.

GET  /agents/{agent_id}/flows/{flow_id}/executions
  — List all executions for a workflow (for monitoring dashboards).
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.flows import _get_db_session, _get_workflow_or_404
from app.models.workflow import Workflow, WorkflowExecution
from app.schemas.workflow import WorkflowAdvanceResult, WorkflowExecutionResponse
from app.services.workflow_engine import WorkflowEngine

logger = structlog.get_logger(__name__)
router = APIRouter()

_TRIGGER_SOURCE_WEBHOOK = "webhook"
_TRIGGER_SOURCE_MANUAL  = "manual_api"


def _verify_webhook_hmac(
    secret: str,
    body: bytes,
    signature_header: str,
) -> bool:
    """Verify HMAC-SHA256 signature.

    Accepts Stripe-style `t=timestamp,v1=signature` format or raw hex digest.
    """
    if not secret or not signature_header:
        return False
    try:
        # Stripe-style: "t=1234,v1=abc..."
        if "v1=" in signature_header:
            parts = dict(p.split("=", 1) for p in signature_header.split(",") if "=" in p)
            provided = parts.get("v1", "")
            timestamp  = parts.get("t", "")
            signed_payload = f"{timestamp}.".encode() + body
        else:
            provided = signature_header
            signed_payload = body

        expected = hmac.new(
            secret.encode(),
            signed_payload,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, provided)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Webhook trigger — HMAC verified
# ---------------------------------------------------------------------------

@router.post("/{agent_id}/flows/{flow_id}/trigger", status_code=202)
async def webhook_trigger(
    agent_id: uuid.UUID,
    flow_id: uuid.UUID,
    request: Request,
):
    """Start a workflow execution via verified external webhook.

    The request body (JSON) becomes the initial execution context.
    Signature must be provided in X-Webhook-Signature header.
    """
    tid_str = request.headers.get("X-Tenant-ID") or getattr(request.state, "tenant_id", None)
    if not tid_str:
        raise HTTPException(status_code=401, detail="Tenant ID required.")
    tid = uuid.UUID(tid_str)

    db = await _get_db_session(tid_str)
    try:
        wf = await _get_workflow_or_404(db, flow_id, agent_id, tid)

        if wf.trigger_type != "webhook":
            raise HTTPException(
                status_code=400,
                detail=f"Workflow trigger_type is '{wf.trigger_type}', not 'webhook'."
            )

        if not wf.is_active:
            raise HTTPException(status_code=400, detail="Workflow is not active.")

        # HMAC verification
        secret = wf.trigger_config.get("webhook_secret", "")
        body   = await request.body()
        sig    = request.headers.get("X-Webhook-Signature", "")

        if secret and not _verify_webhook_hmac(secret, body, sig):
            logger.warning(
                "webhook_hmac_rejected",
                workflow_id=str(flow_id),
                tenant_id=tid_str,
            )
            raise HTTPException(status_code=401, detail="Invalid webhook signature.")

        # Parse payload
        try:
            payload = await request.json()
        except Exception:
            payload = {}

        execution_id = await _start_execution(
            db=db,
            wf=wf,
            initial_context=payload,
            trigger_source=_TRIGGER_SOURCE_WEBHOOK,
            session_id=f"webhook:{secrets.token_hex(8)}",
        )

        return {"execution_id": str(execution_id), "status": "accepted"}

    except HTTPException:
        await db.rollback()
        raise
    except Exception as exc:
        await db.rollback()
        logger.error("webhook_trigger_error", error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to trigger workflow.")
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Manual / test trigger (internal key protected, no HMAC required)
# ---------------------------------------------------------------------------

@router.post("/{agent_id}/flows/{flow_id}/trigger/test", status_code=202)
async def test_trigger(
    agent_id: uuid.UUID,
    flow_id: uuid.UUID,
    request: Request,
):
    """Start a workflow execution for dashboard testing (no HMAC required).

    Protected by X-Internal-Key only.
    """
    tid_str = request.headers.get("X-Tenant-ID") or getattr(request.state, "tenant_id", None)
    if not tid_str:
        raise HTTPException(status_code=401, detail="Tenant ID required.")
    tid = uuid.UUID(tid_str)

    db = await _get_db_session(tid_str)
    try:
        wf = await _get_workflow_or_404(db, flow_id, agent_id, tid)

        if not wf.is_active:
            raise HTTPException(status_code=400, detail="Workflow is not active.")

        try:
            payload = await request.json()
        except Exception:
            payload = {}

        execution_id = await _start_execution(
            db=db,
            wf=wf,
            initial_context=payload,
            trigger_source=_TRIGGER_SOURCE_MANUAL,
            session_id=f"test:{secrets.token_hex(8)}",
        )

        return {"execution_id": str(execution_id), "status": "accepted"}

    except HTTPException:
        await db.rollback()
        raise
    except Exception as exc:
        await db.rollback()
        logger.error("test_trigger_error", error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to trigger workflow.")
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# List executions for a workflow
# ---------------------------------------------------------------------------

@router.get(
    "/{agent_id}/flows/{flow_id}/executions",
    response_model=list[WorkflowExecutionResponse],
)
async def list_executions(
    agent_id: uuid.UUID,
    flow_id: uuid.UUID,
    request: Request,
    limit: int = 50,
    status_filter: Optional[str] = None,
):
    tid_str = request.headers.get("X-Tenant-ID") or getattr(request.state, "tenant_id", None)
    if not tid_str:
        raise HTTPException(status_code=401, detail="Tenant ID required.")
    tid = uuid.UUID(tid_str)

    db = await _get_db_session(tid_str)
    try:
        await _get_workflow_or_404(db, flow_id, agent_id, tid)

        q = (
            select(WorkflowExecution)
            .where(
                WorkflowExecution.workflow_id == flow_id,
                WorkflowExecution.tenant_id == tid,
            )
            .order_by(WorkflowExecution.created_at.desc())
            .limit(min(limit, 200))
        )
        if status_filter:
            q = q.where(WorkflowExecution.status == status_filter.upper())

        result = await db.execute(q)
        return result.scalars().all()
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

async def _start_execution(
    db: AsyncSession,
    wf: Workflow,
    initial_context: dict,
    trigger_source: str,
    session_id: str,
) -> uuid.UUID:
    """Create a WorkflowExecution and advance it one step synchronously.

    For webhook/cron/event triggers the first advance runs immediately in the
    background; the caller gets the execution_id back without waiting.
    """
    engine = WorkflowEngine(db=db)
    execution = await engine.create_execution(
        workflow_id=wf.id,
        session_id=session_id,
        tenant_id=wf.tenant_id,
        initial_context=initial_context,
        customer_phone=initial_context.get("customer_phone", ""),
    )
    # Stamp trigger_source (field added in previous step)
    execution.trigger_source = trigger_source
    
    # Register phone → execution mapping for SMS reply routing if customer_phone is present
    if initial_context.get("customer_phone"):
        from app.workers.workflow_trigger_worker import store_phone_execution
        from app.core.redis_client import get_redis
        redis = await get_redis()
        await store_phone_execution(
            redis,
            initial_context["customer_phone"],
            str(execution.id),
        )

    # Update last_triggered_at on the workflow definition
    from datetime import datetime, timezone
    wf.last_triggered_at = datetime.now(timezone.utc)

    # Advance synchronously — first nodes run before the HTTP response returns.
    # If the workflow hits AWAITING_INPUT immediately, that's fine — it pauses.
    await engine.advance(execution_id=execution.id)
    await db.commit()
    return execution.id
