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
from app.schemas.chat import (
    ChatRequest, 
    ChatResponse, 
    StreamChatEvent, 
    SessionInitRequest, 
    SessionInitResponse
)
from shared.orchestration.memory_manager import MemoryManager
from shared.orchestration.orchestrator import Orchestrator
from app.guardrails.voice_agent_guardrails import get_or_compute_voice_strings

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


def _restricted_agent_id(request: Request) -> uuid.UUID | None:
    """Extract optional agent restriction passed by the API Gateway proxy."""
    raid = request.headers.get("X-Restricted-Agent-ID")
    if raid:
        try:
            return uuid.UUID(raid)
        except ValueError:
            return None
    return None


async def _load_agent(tenant_id: str, agent_id: str, db: AsyncSession, request: Request | None = None) -> Agent:
    agent_uuid = uuid.UUID(agent_id)
    
    # Apply isolation (CRIT-005)
    if request:
        raid = _restricted_agent_id(request)
        if raid and agent_uuid != raid:
            raise HTTPException(status_code=404, detail="Agent not found.")

    result = await db.execute(
        select(Agent).where(
            Agent.id == agent_uuid,
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
    ip_address: Optional[str] = None,
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
        ip_address=ip_address,
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

    agent = await _load_agent(tenant_id, body.agent_id, db, request=request)
    session = await _get_or_create_session(
        body.session_id,
        tenant_id,
        body.agent_id,
        body.channel,
        body.customer_identifier,
        db,
        ip_address=request.headers.get("X-Original-IP"),
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
        test_mode=body.test_mode,
    )
    await db.commit()

    MESSAGES_PROCESSED.labels(channel=body.channel).inc()

    # Store for idempotency deduplication
    if body.idempotency_key:
        await _store_idempotency(body.idempotency_key, tenant_id, response, redis_client)

    return response


@router.post("/init", response_model=SessionInitResponse)
async def session_init(
    body: SessionInitRequest,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
):
    """Initialize a session and return greetings and language options."""
    tenant_id = _tenant_id(request)
    agent = await _load_agent(tenant_id, body.agent_id, db, request=request)
    
    # Create or resume session
    session = await _get_or_create_session(
        session_id=None,  # Always start fresh for init or let the caller provide it if they want to resume?
                          # The requirement says "init api for session init", so usually fresh.
        tenant_id=tenant_id,
        agent_id=body.agent_id,
        channel=body.channel,
        customer_identifier=body.customer_identifier,
        db=db,
        ip_address=request.headers.get("X-Original-IP"),
    )
    # Mark the session as already greeted so that maybe_send_greeting() is a no-op
    # when the first real user message arrives via /stream. Without this flag the
    # billing service would detect msg_count==0, re-emit the greeting into DB/memory,
    # and the LLM would regurgitate it prepended to its first real reply.
    from sqlalchemy.orm.attributes import flag_modified
    session.metadata_ = {"_greeting_sent": True}
    flag_modified(session, "metadata_")
    await db.commit()

    # Determine greetings (Authority logic)
    # Chat greeting
    agent_config = agent.agent_config or {}
    chat_greeting = agent_config.get("greeting_message") or "Hi! How can I help you today?"
    
    # Voice greeting prioritization
    # Use the same computation logic as the Agents API for consistency
    computed_greeting, _, _ = await get_or_compute_voice_strings(db, agent)
    
    voice_greeting = "Hi! How can I help you today?"
    if agent_config.get("ivr_language_prompt"):
        voice_greeting = agent_config["ivr_language_prompt"]
    elif computed_greeting:
        voice_greeting = computed_greeting
    else:
        voice_greeting = chat_greeting

    return SessionInitResponse(
        session_id=str(session.id),
        chat_greeting=chat_greeting,
        voice_greeting=voice_greeting,
        language=agent.language or "en",
        supported_languages=agent_config.get("supported_languages") or [],
        auto_detect_language=agent_config.get("auto_detect_language") or False,
    )


@router.post("/agent-call")
async def agent_call(
    body: dict,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
):
    """Called by the MCP server (agent_call tool) to invoke an agent programmatically.

    Accepts: agent_id, message, context, tenant_id
    Returns: {"response": str}
    """
    agent_id = body.get("agent_id", "")
    message = body.get("message", "")
    context = body.get("context", "")
    tenant_id = (
        body.get("tenant_id")
        or request.headers.get("X-Tenant-ID")
        or getattr(request.state, "tenant_id", None)
    )

    if not tenant_id:
        raise HTTPException(status_code=401, detail="Tenant ID required.")
    if not agent_id:
        raise HTTPException(status_code=400, detail="agent_id is required.")
    if not message:
        raise HTTPException(status_code=400, detail="message is required.")

    # Fetch and validate agent — must be active and available as a tool
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

    if not getattr(agent, "is_available_as_tool", True):
        raise HTTPException(
            status_code=403,
            detail="This agent is not available for tool invocation.",
        )

    # Prepend context to message if provided
    full_message = f"[Context: {context}]\n\n{message}" if context else message

    # Create a transient session for this agent-to-agent call
    redis_client = getattr(request.app.state, "redis", None)
    llm_client = getattr(request.app.state, "llm_client", None)
    mcp_client = getattr(request.app.state, "mcp_client", None)
    moderation_service = getattr(request.app.state, "moderation_service", None)

    session = await _get_or_create_session(
        session_id=None,
        tenant_id=tenant_id,
        agent_id=agent_id,
        channel="agent_call",
        customer_identifier="agent_caller",
        db=db,
        ip_address="internal",
    )

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
        user_message=full_message,
        stream=False,
    )
    await db.commit()

    logger.info(
        "agent_call_completed",
        agent_id=agent_id,
        tenant_id=tenant_id,
        latency_ms=response.latency_ms,
    )

    return {"response": response.message, "agent_id": agent_id, "session_id": session.id}


@router.post("/stream")
async def chat_stream(
    body: ChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
):
    """Stream a chat response as Server-Sent Events."""
    tenant_id = _tenant_id(request)
    agent = await _load_agent(tenant_id, body.agent_id, db, request=request)
    session = await _get_or_create_session(
        body.session_id,
        tenant_id,
        body.agent_id,
        body.channel,
        body.customer_identifier,
        db,
        ip_address=request.headers.get("X-Original-IP"),
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
                agent=agent, session=session, user_message=body.message,
                test_mode=body.test_mode
            ):
                yield f"data: {_json.dumps({'type': event.type, 'data': event.data, 'session_id': event.session_id})}\n\n"
        except Exception as exc:
            logger.error("stream_error", session_id=str(session.id), error=str(exc))
            yield f"data: {_json.dumps({'type': 'error', 'data': f'Error: {str(exc)}', 'session_id': str(session.id)})}\n\n"
        finally:
            # Always commit — whether the stream succeeded or raised an exception.
            # This ensures partial writes (user message, session state) are persisted.
            try:
                await db.commit()
            except Exception as commit_exc:
                logger.error("stream_commit_error", session_id=str(session.id), error=str(commit_exc))

    return StreamingResponse(event_generator(), media_type="text/event-stream")
