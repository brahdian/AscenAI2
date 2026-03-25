from __future__ import annotations

import time
import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.agent import Agent, Session as AgentSession
from app.schemas.chat import ChatRequest, ChatResponse, StreamChatEvent
from app.services.memory_manager import MemoryManager
from app.services.orchestrator import Orchestrator

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/chat")


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
            return sess

    new_id = session_id or str(uuid.uuid4())
    sess = AgentSession(
        id=new_id,
        tenant_id=uuid.UUID(tenant_id),
        agent_id=uuid.UUID(agent_id),
        customer_identifier=customer_identifier,
        channel=channel,
        status="active",
    )
    db.add(sess)
    await db.flush()
    return sess


@router.post("", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Process a chat message and return the AI response."""
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

    memory_manager = MemoryManager(redis_client=redis_client, db=db)
    orchestrator = Orchestrator(
        llm_client=llm_client,
        mcp_client=mcp_client,
        memory_manager=memory_manager,
        db=db,
        redis_client=redis_client,
    )

    response = await orchestrator.process_message(
        agent=agent,
        session=session,
        user_message=body.message,
        stream=False,
    )
    await db.commit()
    return response


@router.post("/stream")
async def chat_stream(
    body: ChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
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

    memory_manager = MemoryManager(redis_client=redis_client, db=db)
    orchestrator = Orchestrator(
        llm_client=llm_client,
        mcp_client=mcp_client,
        memory_manager=memory_manager,
        db=db,
        redis_client=redis_client,
    )

    async def event_generator():
        try:
            async for event in orchestrator.stream_response(
                agent=agent, session=session, user_message=body.message
            ):
                import json
                yield f"data: {json.dumps({'type': event.type, 'data': event.data, 'session_id': event.session_id})}\n\n"
            await db.commit()
        except Exception as exc:
            import json
            logger.error("stream_error", session_id=str(session.id), error=str(exc))
            yield f"data: {json.dumps({'type': 'error', 'data': 'An internal error occurred', 'session_id': str(session.id)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
