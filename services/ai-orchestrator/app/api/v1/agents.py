from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.agent import Agent, AgentPlaybook
from app.schemas.chat import (
    AgentCreate,
    AgentResponse,
    AgentTestRequest,
    AgentUpdate,
    ChatResponse,
)

logger = structlog.get_logger(__name__)
router = APIRouter()


def _tenant_id(request: Request) -> str:
    tid = request.headers.get("X-Tenant-ID") or getattr(request.state, "tenant_id", None)
    if not tid:
        raise HTTPException(status_code=401, detail="Tenant ID required.")
    return tid


def _agent_to_response(agent: Agent) -> AgentResponse:
    return AgentResponse(
        id=str(agent.id),
        tenant_id=str(agent.tenant_id),
        name=agent.name,
        description=agent.description,
        business_type=agent.business_type,
        personality=agent.personality,
        system_prompt=agent.system_prompt,
        voice_enabled=agent.voice_enabled,
        voice_id=agent.voice_id,
        language=agent.language,
        tools=agent.tools or [],
        knowledge_base_ids=agent.knowledge_base_ids or [],
        llm_config=agent.llm_config or {},
        escalation_config=agent.escalation_config or {},
        is_active=agent.is_active,
        created_at=agent.created_at.isoformat() if agent.created_at else None,
        updated_at=agent.updated_at.isoformat() if agent.updated_at else None,
    )


@router.post("", response_model=AgentResponse, status_code=201)
async def create_agent(
    body: AgentCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Create a new AI agent for the tenant."""
    tenant_id = _tenant_id(request)
    agent = Agent(
        id=uuid.uuid4(),
        tenant_id=uuid.UUID(tenant_id),
        name=body.name,
        description=body.description,
        business_type=body.business_type,
        personality=body.personality,
        system_prompt=body.system_prompt,
        voice_enabled=body.voice_enabled,
        voice_id=body.voice_id,
        language=body.language,
        tools=body.tools,
        knowledge_base_ids=body.knowledge_base_ids,
        llm_config=body.llm_config,
        escalation_config=body.escalation_config,
        is_active=True,
    )
    db.add(agent)

    # Auto-create a default playbook so the agent is ready to use immediately
    default_playbook = AgentPlaybook(
        id=uuid.uuid4(),
        agent_id=agent.id,
        tenant_id=agent.id,  # will be overridden below after commit
        name="Default",
        description="Default playbook — edit to add instructions for your agent.",
        is_default=True,
        intent_triggers=[],
        greeting_message=f"Hi! I'm {body.name}. How can I help you today?",
        instructions=body.system_prompt or "",
        tone=body.personality or "professional",
    )
    # Set the correct tenant_id
    default_playbook.tenant_id = uuid.UUID(tenant_id)
    db.add(default_playbook)

    await db.commit()
    await db.refresh(agent)
    logger.info("agent_created", agent_id=str(agent.id), tenant_id=tenant_id)
    return _agent_to_response(agent)


@router.get("", response_model=list[AgentResponse])
async def list_agents(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """List all active agents for the tenant."""
    tenant_id = _tenant_id(request)
    result = await db.execute(
        select(Agent)
        .where(Agent.tenant_id == uuid.UUID(tenant_id), Agent.is_active.is_(True))
        .order_by(Agent.created_at.desc())
    )
    return [_agent_to_response(a) for a in result.scalars().all()]


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Get a specific agent by ID."""
    tenant_id = _tenant_id(request)
    result = await db.execute(
        select(Agent).where(
            Agent.id == uuid.UUID(agent_id),
            Agent.tenant_id == uuid.UUID(tenant_id),
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found.")
    return _agent_to_response(agent)


@router.patch("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: str,
    body: AgentUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Update an agent's configuration."""
    tenant_id = _tenant_id(request)
    result = await db.execute(
        select(Agent).where(
            Agent.id == uuid.UUID(agent_id),
            Agent.tenant_id == uuid.UUID(tenant_id),
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found.")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(agent, field, value)

    await db.commit()
    await db.refresh(agent)
    return _agent_to_response(agent)


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(
    agent_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Deactivate an agent."""
    tenant_id = _tenant_id(request)
    result = await db.execute(
        select(Agent).where(
            Agent.id == uuid.UUID(agent_id),
            Agent.tenant_id == uuid.UUID(tenant_id),
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found.")
    agent.is_active = False
    await db.commit()


@router.post("/{agent_id}/test", response_model=ChatResponse)
async def test_agent(
    agent_id: str,
    body: AgentTestRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Send a test message to an agent."""
    from app.schemas.chat import ChatRequest
    chat_body = ChatRequest(
        agent_id=agent_id,
        message=body.message,
        channel="text",
        customer_identifier=body.customer_identifier or "test-user",
    )
    # Delegate to the chat endpoint
    from app.api.v1.chat import chat
    return await chat(chat_body, request, db)
