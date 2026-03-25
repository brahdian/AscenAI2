from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.agent import Agent, AgentPlaybook
from app.schemas.chat import PlaybookResponse, PlaybookUpsert

logger = structlog.get_logger(__name__)
router = APIRouter()


def _tenant_id(request: Request) -> str:
    tid = request.headers.get("X-Tenant-ID") or getattr(request.state, "tenant_id", None)
    if not tid:
        raise HTTPException(status_code=401, detail="Tenant ID required.")
    return tid


def _to_response(pb: AgentPlaybook) -> PlaybookResponse:
    return PlaybookResponse(
        id=str(pb.id),
        agent_id=str(pb.agent_id),
        tenant_id=str(pb.tenant_id),
        greeting_message=pb.greeting_message,
        instructions=pb.instructions,
        tone=pb.tone,
        dos=pb.dos or [],
        donts=pb.donts or [],
        scenarios=pb.scenarios or [],
        out_of_scope_response=pb.out_of_scope_response,
        fallback_response=pb.fallback_response,
        custom_escalation_message=pb.custom_escalation_message,
        is_active=pb.is_active,
        created_at=pb.created_at.isoformat() if pb.created_at else "",
        updated_at=pb.updated_at.isoformat() if pb.updated_at else "",
    )


async def _verify_agent(agent_id: str, tenant_id: str, db: AsyncSession) -> Agent:
    result = await db.execute(
        select(Agent).where(
            Agent.id == uuid.UUID(agent_id),
            Agent.tenant_id == uuid.UUID(tenant_id),
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found.")
    return agent


@router.get("/{agent_id}/playbook", response_model=PlaybookResponse)
async def get_playbook(
    agent_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Get the playbook for an agent. Returns 404 if not yet configured."""
    tenant_id = _tenant_id(request)
    await _verify_agent(agent_id, tenant_id, db)

    result = await db.execute(
        select(AgentPlaybook).where(AgentPlaybook.agent_id == uuid.UUID(agent_id))
    )
    pb = result.scalar_one_or_none()
    if not pb:
        raise HTTPException(status_code=404, detail="Playbook not configured yet.")
    return _to_response(pb)


@router.put("/{agent_id}/playbook", response_model=PlaybookResponse)
async def upsert_playbook(
    agent_id: str,
    body: PlaybookUpsert,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Create or fully replace the playbook for an agent."""
    tenant_id = _tenant_id(request)
    agent = await _verify_agent(agent_id, tenant_id, db)

    result = await db.execute(
        select(AgentPlaybook).where(AgentPlaybook.agent_id == agent.id)
    )
    pb = result.scalar_one_or_none()

    if pb is None:
        pb = AgentPlaybook(
            agent_id=agent.id,
            tenant_id=agent.tenant_id,
        )
        db.add(pb)

    pb.greeting_message = body.greeting_message
    pb.instructions = body.instructions
    pb.tone = body.tone
    pb.dos = body.dos
    pb.donts = body.donts
    pb.scenarios = [s.model_dump() for s in body.scenarios]
    pb.out_of_scope_response = body.out_of_scope_response
    pb.fallback_response = body.fallback_response
    pb.custom_escalation_message = body.custom_escalation_message
    pb.is_active = body.is_active

    await db.commit()
    await db.refresh(pb)
    logger.info("playbook_upserted", agent_id=agent_id)
    return _to_response(pb)


@router.delete("/{agent_id}/playbook", status_code=204)
async def delete_playbook(
    agent_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Remove the playbook for an agent."""
    tenant_id = _tenant_id(request)
    await _verify_agent(agent_id, tenant_id, db)

    result = await db.execute(
        select(AgentPlaybook).where(AgentPlaybook.agent_id == uuid.UUID(agent_id))
    )
    pb = result.scalar_one_or_none()
    if pb:
        await db.delete(pb)
        await db.commit()
