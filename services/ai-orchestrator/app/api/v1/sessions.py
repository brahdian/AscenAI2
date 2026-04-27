from __future__ import annotations

import re
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_tenant_db
from app.models.agent import Message, MessageFeedback, Session as AgentSession
from app.schemas.chat import SessionAnalyticsResponse, SessionResponse

logger = structlog.get_logger(__name__)
router = APIRouter()

# ---------------------------------------------------------------------------
# Server-side PII redaction for message content sent to the dashboard UI.
# This ensures raw PII never crosses the wire to the browser, even if a
# message was persisted before the orchestrator-level pseudonymization was
# fully in place.
# ---------------------------------------------------------------------------
import shared.pii as pii_service


def _tenant_id(request: Request) -> str:
    """Extract tenant_id stamped by the AuthMiddleware onto request.state.

    SECURITY: We read from request.state (set by the hardened AuthMiddleware
    after full JWT/API-key validation) rather than directly from the
    X-Tenant-ID header, which can be spoofed by any caller.
    
    However, for internal proxy requests from the API Gateway, we also accept
    the X-Tenant-ID header which is already validated by the gateway.
    """
    tid = getattr(request.state, "tenant_id", None)
    if not tid:
        # Fallback for internal proxy requests from API Gateway
        tid = request.headers.get("X-Tenant-ID")
    if not tid:
        raise HTTPException(status_code=401, detail="Tenant ID required.")
    return tid


def _restricted_agent_id(request: Request) -> uuid.UUID | None:
    """Extract optional agent restriction passed by the API Gateway proxy.
    
    If present, this indicates that the caller (e.g., a Widget Key) is 
    STRICTLY restricted to this specific agent.
    """
    raid = request.headers.get("X-Restricted-Agent-ID")
    if raid:
        try:
            return uuid.UUID(raid)
        except ValueError:
            return None
    return None


def _session_to_response(
    sess: AgentSession,
    messages: list | None = None,
    feedback_map: dict | None = None,
    request: Request | None = None,
) -> SessionResponse:
    msg_list = None
    if messages is not None:
        msg_list = []
        for m in messages:
            fb = (feedback_map or {}).get(str(m.id))
            
            # PII Redaction for complex fields (tool_calls, sources) using deep recursive logic
            redacted_tool_calls = pii_service.redact_deep(m.tool_calls) if m.tool_calls else None
            redacted_sources = pii_service.redact_deep(m.sources) if m.sources else None

            msg_list.append({
                "id": str(m.id),
                "role": m.role,
                "content": pii_service.redact_for_display(m.content, None),
                "tokens_used": m.tokens_used,
                "latency_ms": m.latency_ms,
                "tool_calls": redacted_tool_calls,
                "playbook_name": m.playbook_name,
                "sources": redacted_sources,
                "created_at": m.created_at.isoformat() if m.created_at else None,
                "feedback": fb,
            })
    expiry_minutes = getattr(settings, "SESSION_EXPIRY_MINUTES", 30)
    # Standardize redaction for restricted keys (Widget Keys)
    raid = _restricted_agent_id(request) if request else None
    
    customer_id = sess.customer_identifier
    metadata = sess.metadata_ if hasattr(sess, "metadata_") else {}
    
    if raid:
        customer_id = pii_service.redact(customer_id) if customer_id else customer_id
        # Redact any string values in metadata for safety
        metadata = {k: (pii_service.redact(v) if isinstance(v, str) else v) for k, v in metadata.items()}

    return SessionResponse(
        id=str(sess.id),
        tenant_id=str(sess.tenant_id),
        agent_id=str(sess.agent_id),
        customer_identifier=customer_id,
        channel=sess.channel,
        status=sess.status,
        metadata=metadata,
        started_at=sess.started_at.isoformat() if hasattr(sess, "started_at") and sess.started_at else None,
        ended_at=sess.ended_at.isoformat() if hasattr(sess, "ended_at") and sess.ended_at else None,
        last_activity_at=sess.last_activity_at.isoformat() if hasattr(sess, "last_activity_at") and sess.last_activity_at else None,
        updated_at=sess.updated_at.isoformat() if hasattr(sess, "updated_at") and sess.updated_at else None,
        messages=msg_list,
        minutes_until_expiry=round(sess.minutes_until_expiry(expiry_minutes), 1) if sess.status == "active" else None,
    )


@router.get("", response_model=list[SessionResponse])
async def list_sessions(
    request: Request,
    agent_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_tenant_db),
):
    """List sessions for the tenant."""
    tenant_id = _tenant_id(request)
    query = (
        select(AgentSession)
        .where(AgentSession.tenant_id == uuid.UUID(tenant_id))
        .order_by(AgentSession.started_at.desc(), AgentSession.id.desc())
        .limit(min(limit, 200))
    )
    if agent_id:
        query = query.where(AgentSession.agent_id == uuid.UUID(agent_id))
    
    # Apply deep isolation restriction if present (CRIT-005)
    raid = _restricted_agent_id(request)
    if raid:
        query = query.where(AgentSession.agent_id == raid)

    if status:
        query = query.where(AgentSession.status == status)

    result = await db.execute(query)
    return [_session_to_response(s, request=request) for s in result.scalars().all()]


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: str,
    request: Request,
    include_messages: bool = False,
    db: AsyncSession = Depends(get_tenant_db),
):
    """Get a specific session, optionally with messages."""
    tenant_id = _tenant_id(request)

    query = select(AgentSession).where(
        AgentSession.id == session_id,
        AgentSession.tenant_id == uuid.UUID(tenant_id),
    )
    
    # Apply deep isolation restriction if present (CRIT-005)
    raid = _restricted_agent_id(request)
    if raid:
        query = query.where(AgentSession.agent_id == raid)

    result = await db.execute(query)
    sess = result.scalar_one_or_none()
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found.")

    messages = None
    feedback_map = None
    if include_messages:
        msg_result = await db.execute(
            select(Message)
            .where(
                Message.session_id == session_id,
                Message.tenant_id == uuid.UUID(tenant_id),
            )
            .order_by(Message.created_at.asc())
        )
        messages = list(msg_result.scalars().all())

        # Load any existing feedback for these messages
        if messages:
            message_ids = [m.id for m in messages]
            fb_result = await db.execute(
                select(MessageFeedback).where(
                    MessageFeedback.message_id.in_(message_ids)
                )
            )
            feedback_map = {
                str(fb.message_id): {
                    "id": str(fb.id),
                    "rating": fb.rating,
                    "labels": fb.labels or [],
                    "comment": pii_service.redact_for_display(fb.comment, None),
                    "ideal_response": pii_service.redact_for_display(fb.ideal_response, None),
                    "correction_reason": pii_service.redact_for_display(fb.correction_reason, None),
                    "playbook_correction": fb.playbook_correction,
                    "tool_corrections": fb.tool_corrections or [],
                }
                for fb in fb_result.scalars().all()
            }

    return _session_to_response(sess, messages, feedback_map, request=request)


@router.post("/{session_id}/end", response_model=SessionResponse)
async def end_session(
    session_id: str,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
):
    """Mark a session as ended."""
    tenant_id = _tenant_id(request)
    
    query = select(AgentSession).where(
        AgentSession.id == session_id,
        AgentSession.tenant_id == uuid.UUID(tenant_id),
    )
    
    raid = _restricted_agent_id(request)
    if raid:
        query = query.where(AgentSession.agent_id == raid)

    result = await db.execute(query)
    sess = result.scalar_one_or_none()
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found.")

    sess.status = "ended"
    if hasattr(sess, "ended_at"):
        from datetime import datetime, timezone
        sess.ended_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(sess)
    return _session_to_response(sess, request=request)


@router.get("/{session_id}/analytics", response_model=SessionAnalyticsResponse)
async def session_analytics(
    session_id: str,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
):
    """Get analytics for a session."""
    tenant_id = _tenant_id(request)
    
    query = select(AgentSession).where(
        AgentSession.id == session_id,
        AgentSession.tenant_id == uuid.UUID(tenant_id),
    )
    
    raid = _restricted_agent_id(request)
    if raid:
        query = query.where(AgentSession.agent_id == raid)

    result = await db.execute(query)
    sess = result.scalar_one_or_none()
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found.")

    msg_result = await db.execute(
        select(Message).where(
            Message.session_id == session_id,
            Message.tenant_id == uuid.UUID(tenant_id),
        )
    )
    messages = list(msg_result.scalars().all())

    user_msgs = [m for m in messages if m.role == "user"]
    assistant_msgs = [m for m in messages if m.role == "assistant"]
    total_tokens = sum(getattr(m, "tokens_used", 0) or 0 for m in messages)
    total_latency = sum(getattr(m, "latency_ms", 0) or 0 for m in assistant_msgs)
    tool_calls = sum(len(getattr(m, "tool_calls", None) or []) for m in messages)

    duration = None
    if hasattr(sess, "started_at") and hasattr(sess, "ended_at"):
        if sess.started_at and sess.ended_at:
            duration = (sess.ended_at - sess.started_at).total_seconds()

    return SessionAnalyticsResponse(
        session_id=session_id,
        total_messages=len(messages),
        user_messages=len(user_msgs),
        assistant_messages=len(assistant_msgs),
        total_tokens=total_tokens,
        total_latency_ms=total_latency,
        avg_latency_ms=total_latency / len(assistant_msgs) if assistant_msgs else 0.0,
        tool_calls_made=tool_calls,
        duration_seconds=duration,
        status=sess.status,
    )
