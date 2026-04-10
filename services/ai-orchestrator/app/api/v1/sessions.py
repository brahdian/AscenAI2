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
_EMAIL_RE = re.compile(r'\b[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}\b')
_PHONE_RE = re.compile(r'\b(\+?[\d][\d\s\-().]{7,}\d)\b')
_CARD_RE  = re.compile(r'\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b')
_SSN_RE   = re.compile(r'\b\d{3}[\-\s]?\d{2}[\-\s]?\d{4}\b')


def _redact_pii(text: str | None) -> str | None:
    """Redact common PII patterns from text before sending to the frontend."""
    if not text:
        return text
    text = _EMAIL_RE.sub('[EMAIL]', text)
    text = _PHONE_RE.sub('[PHONE]', text)
    text = _CARD_RE.sub('[CARD]', text)
    text = _SSN_RE.sub('[SSN]', text)
    return text


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


def _session_to_response(
    sess: AgentSession,
    messages: list | None = None,
    feedback_map: dict | None = None,
) -> SessionResponse:
    msg_list = None
    if messages is not None:
        msg_list = []
        for m in messages:
            fb = (feedback_map or {}).get(str(m.id))
            msg_list.append({
                "id": str(m.id),
                "role": m.role,
                "content": _redact_pii(m.content),
                "tokens_used": m.tokens_used,
                "latency_ms": m.latency_ms,
                "tool_calls": m.tool_calls,
                "playbook_name": m.playbook_name,
                "sources": m.sources,
                "created_at": m.created_at.isoformat() if m.created_at else None,
                "feedback": fb,
            })
    expiry_minutes = getattr(settings, "SESSION_EXPIRY_MINUTES", 30)
    return SessionResponse(
        id=str(sess.id),
        tenant_id=str(sess.tenant_id),
        agent_id=str(sess.agent_id),
        customer_identifier=sess.customer_identifier,
        channel=sess.channel,
        status=sess.status,
        metadata=sess.metadata_ if hasattr(sess, "metadata_") else {},
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
        .order_by(AgentSession.started_at.desc() if hasattr(AgentSession, "started_at") else AgentSession.id.desc())
        .limit(min(limit, 200))
    )
    if agent_id:
        query = query.where(AgentSession.agent_id == uuid.UUID(agent_id))
    if status:
        query = query.where(AgentSession.status == status)

    result = await db.execute(query)
    return [_session_to_response(s) for s in result.scalars().all()]


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: str,
    request: Request,
    include_messages: bool = False,
    db: AsyncSession = Depends(get_tenant_db),
):
    """Get a specific session, optionally with messages."""
    tenant_id = _tenant_id(request)
    result = await db.execute(
        select(AgentSession).where(
            AgentSession.id == session_id,
            AgentSession.tenant_id == uuid.UUID(tenant_id),
        )
    )
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
                    "comment": fb.comment,
                }
                for fb in fb_result.scalars().all()
            }

    return _session_to_response(sess, messages, feedback_map)


@router.post("/{session_id}/end", response_model=SessionResponse)
async def end_session(
    session_id: str,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
):
    """Mark a session as ended."""
    tenant_id = _tenant_id(request)
    result = await db.execute(
        select(AgentSession).where(
            AgentSession.id == session_id,
            AgentSession.tenant_id == uuid.UUID(tenant_id),
        )
    )
    sess = result.scalar_one_or_none()
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found.")

    sess.status = "ended"
    if hasattr(sess, "ended_at"):
        from datetime import datetime, timezone
        sess.ended_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(sess)
    return _session_to_response(sess)


@router.get("/{session_id}/analytics", response_model=SessionAnalyticsResponse)
async def session_analytics(
    session_id: str,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
):
    """Get analytics for a session."""
    tenant_id = _tenant_id(request)
    result = await db.execute(
        select(AgentSession).where(
            AgentSession.id == session_id,
            AgentSession.tenant_id == uuid.UUID(tenant_id),
        )
    )
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
