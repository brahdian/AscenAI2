from __future__ import annotations

import json as _json
import time
import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_tenant_db
from app.core.metrics import MESSAGES_PROCESSED, SESSIONS_CREATED
from app.models.agent import Agent, Session as AgentSession
from app.schemas.chat import ChatRequest, ChatResponse, StreamChatEvent
from app.services.memory_manager import MemoryManager
from app.services.orchestrator import Orchestrator

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/chat")

_IDEMPOTENCY_TTL = 300  # 5 minutes


async def _check_idempotency(key: str, tenant_id: str, redis) -> Optional[ChatResponse]:
    """Return cached ChatResponse if key was seen recently, else None."""
    if not key or redis is None:
        return None
    try:
        cached = await redis.get(f"tenant:{tenant_id}:idem:chat:{key}")
        if cached:
            return ChatResponse(**_json.loads(cached))
    except Exception:
        pass
    return None


async def _store_idempotency(key: str, tenant_id: str, response: ChatResponse, redis) -> None:
    """Cache the response under the idempotency key for TTL seconds."""
    if not key or redis is None:
        return
    try:
        await redis.setex(f"tenant:{tenant_id}:idem:chat:{key}", _IDEMPOTENCY_TTL, _json.dumps(response.model_dump()))
    except Exception:
        pass


def _tenant_id(request: Request) -> str:
    tid = request.headers.get("X-Tenant-ID") or getattr(request.state, "tenant_id", None)
    if not tid:
        raise HTTPException(status_code=401, detail="Tenant ID required.")
    return tid


async def _load_agent(tenant_id: str, agent_id: str, db: AsyncSession) -> Agent:
    result = await db.execute(
        select(Agent).where(
            Agent.id == uuid.UUID(agent_id),
            Agent.tenant_id == uuid.UUID(tenant_id),
            Agent.is_active.is_(True),
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found or inactive.")
    return agent


async def _get_or_create_session(
    session_id: Optional[str],
    tenant_id: str,
    agent_id: str,
    channel: str,
    customer_identifier: Optional[str],
    db: AsyncSession,
) -> AgentSession:
    if session_id:
        result = await db.execute(
            select(AgentSession).where(
                AgentSession.id == session_id,
                AgentSession.tenant_id == uuid.UUID(tenant_id),
            )
        )
        sess = result.scalar_one_or_none()
        if sess:
            # Auto-close expired sessions
            from app.core.config import settings as _settings
            expiry_minutes = getattr(_settings, "SESSION_EXPIRY_MINUTES", 30)
            if sess.is_expired(expiry_minutes):
                sess.close()
                await db.flush()
                logger.info("expired_session_replaced", old_session_id=session_id)
                # Fall through to create a new session with a new ID
            else:
                return sess

    from datetime import datetime, timezone as _tz
    # Always generate a new ID when creating a fresh session
    new_id = str(uuid.uuid4())
    sess = AgentSession(
        id=new_id,
        tenant_id=uuid.UUID(tenant_id),
        agent_id=uuid.UUID(agent_id),
        customer_identifier=customer_identifier,
        channel=channel,
        status="active",
        last_activity_at=datetime.now(_tz.utc),
    )
    db.add(sess)
    await db.flush()
    SESSIONS_CREATED.labels(channel=channel).inc()
    return sess


@router.post("", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
):
    """Process a chat message and return the AI response."""
    tenant_id = _tenant_id(request)
    redis_client = getattr(request.app.state, "redis", None)

    # Idempotency check — return cached response for duplicate client retries
    if body.idempotency_key:
        cached = await _check_idempotency(body.idempotency_key, tenant_id, redis_client)
        if cached:
            logger.info("chat_idempotent_hit", key=body.idempotency_key, session_id=body.session_id)
            return cached

    agent = await _load_agent(tenant_id, body.agent_id, db)
    session = await _get_or_create_session(
        body.session_id,
        tenant_id,
        body.agent_id,
        body.channel,
        body.customer_identifier,
        db,
    )

    llm_client = getattr(request.app.state, "llm_client", None)
    mcp_client = getattr(request.app.state, "mcp_client", None)
    moderation_service = getattr(request.app.state, "moderation_service", None)

    memory_manager = MemoryManager(redis_client=redis_client, db=db)
    orchestrator = Orchestrator(
        llm_client=llm_client,
        mcp_client=mcp_client,
        memory_manager=memory_manager,
        db=db,
        redis_client=redis_client,
        moderation_service=moderation_service,
    )

    response = await orchestrator.process_message(
        agent=agent,
        session=session,
        user_message=body.message,
        stream=False,
    )
    await db.commit()

    MESSAGES_PROCESSED.labels(channel=body.channel).inc()

    # Store for idempotency deduplication
    if body.idempotency_key:
        await _store_idempotency(body.idempotency_key, tenant_id, response, redis_client)

    return response


@router.post("/stream")
async def chat_stream(
    body: ChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
):
    """Stream a chat response as Server-Sent Events."""
    tenant_id = _tenant_id(request)
    agent = await _load_agent(tenant_id, body.agent_id, db)
    session = await _get_or_create_session(
        body.session_id,
        tenant_id,
        body.agent_id,
        body.channel,
        body.customer_identifier,
        db,
    )

    redis_client = getattr(request.app.state, "redis", None)
    llm_client = getattr(request.app.state, "llm_client", None)
    mcp_client = getattr(request.app.state, "mcp_client", None)
    moderation_service = getattr(request.app.state, "moderation_service", None)

    memory_manager = MemoryManager(redis_client=redis_client, db=db)
    orchestrator = Orchestrator(
        llm_client=llm_client,
        mcp_client=mcp_client,
        memory_manager=memory_manager,
        db=db,
        redis_client=redis_client,
        moderation_service=moderation_service,
    )

    async def event_generator():
        import json as _json
        try:
            # Emit session id immediately so the frontend can correlate the stream
            yield f"data: {_json.dumps({'type': 'session', 'data': str(session.id), 'session_id': str(session.id)})}\n\n"
            async for event in orchestrator.stream_response(
                agent=agent, session=session, user_message=body.message
            ):
                yield f"data: {_json.dumps({'type': event.type, 'data': event.data, 'session_id': event.session_id})}\n\n"
        except Exception as exc:
            logger.error("stream_error", session_id=str(session.id), error=str(exc))
            yield f"data: {_json.dumps({'type': 'error', 'data': 'An internal error occurred', 'session_id': str(session.id)})}\n\n"
        finally:
            # Always commit — whether the stream succeeded or raised an exception.
            # This ensures partial writes (user message, session state) are persisted.
            try:
                await db.commit()
            except Exception as commit_exc:
                logger.error("stream_commit_error", session_id=str(session.id), error=str(commit_exc))

    return StreamingResponse(event_generator(), media_type="text/event-stream")
