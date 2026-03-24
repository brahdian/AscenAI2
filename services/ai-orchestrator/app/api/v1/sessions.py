from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.agent import Message, Session as AgentSession
from app.schemas.chat import SessionAnalyticsResponse, SessionResponse

logger = structlog.get_logger(__name__)
router = APIRouter()


def _tenant_id(request: Request) -> str:
    tid = request.headers.get("X-Tenant-ID") or getattr(request.state, "tenant_id", None)
    if not tid:
        raise HTTPException(status_code=401, detail="Tenant ID required.")
    return tid


def _session_to_response(sess: AgentSession, messages: list | None = None) -> SessionResponse:
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
        updated_at=sess.updated_at.isoformat() if hasattr(sess, "updated_at") and sess.updated_at else None,
        messages=[
            {"role": m.role, "content": m.content, "created_at": m.created_at.isoformat() if m.created_at else None}
            for m in (messages or [])
        ] if messages is not None else None,
    )


@router.get("", response_model=list[SessionResponse])
async def list_sessions(
    request: Request,
    agent_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
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
    db: AsyncSession = Depends(get_db),
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
    if include_messages:
        msg_result = await db.execute(
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.created_at.asc())
        )
        messages = list(msg_result.scalars().all())

    return _session_to_response(sess, messages)


@router.post("/{session_id}/end", response_model=SessionResponse)
async def end_session(
    session_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
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
    db: AsyncSession = Depends(get_db),
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
        select(Message).where(Message.session_id == session_id)
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
