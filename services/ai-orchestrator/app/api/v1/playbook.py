from __future__ import annotations

import copy
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
    config = pb.config or {}
    return PlaybookResponse(
        id=str(pb.id),
        agent_id=str(pb.agent_id),
        tenant_id=str(pb.tenant_id),
        name=pb.name,
        description=pb.description,
        intent_triggers=pb.intent_triggers or [],
        is_default=pb.is_default,
        instructions=config.get("instructions"),
        tone=config.get("tone", "professional"),
        dos=config.get("dos", []),
        donts=config.get("donts", []),
        scenarios=config.get("scenarios", []),
        out_of_scope_response=config.get("out_of_scope_response"),
        fallback_response=config.get("fallback_response"),
        custom_escalation_message=config.get("custom_escalation_message"),
        is_active=pb.is_active,
        created_at=pb.created_at.isoformat() if pb.created_at else "",
        updated_at=pb.updated_at.isoformat() if pb.updated_at else "",
        config=config,
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


@router.get("/{agent_id}/playbooks", response_model=list[PlaybookResponse])
async def list_playbooks(
    agent_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """List all playbooks for an agent."""
    tenant_id = _tenant_id(request)
    await _verify_agent(agent_id, tenant_id, db)

    result = await db.execute(
        select(AgentPlaybook)
        .where(AgentPlaybook.agent_id == uuid.UUID(agent_id))
        .order_by(AgentPlaybook.is_default.desc(), AgentPlaybook.created_at.asc())
    )
    return [_to_response(pb) for pb in result.scalars().all()]


@router.post("/{agent_id}/playbooks", response_model=PlaybookResponse, status_code=201)
async def create_playbook(
    agent_id: str,
    body: PlaybookUpsert,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Create a new playbook for an agent."""
    tenant_id = _tenant_id(request)
    agent = await _verify_agent(agent_id, tenant_id, db)

    if body.is_default:
        existing_defaults = await db.execute(
            select(AgentPlaybook).where(
                AgentPlaybook.agent_id == agent.id,
                AgentPlaybook.is_default.is_(True),
            )
        )
        for pb in existing_defaults.scalars().all():
            pb.is_default = False

    incoming = body.config.copy() if body.config else {}
    if not incoming:
        incoming = {"tone": "professional", "dos": [], "donts": [], "scenarios": []}

    pb = AgentPlaybook(
        agent_id=agent.id,
        tenant_id=agent.tenant_id,
        name=body.name,
        description=body.description,
        intent_triggers=body.intent_triggers,
        is_default=body.is_default,
        config=incoming,
        is_active=body.is_active,
    )
    db.add(pb)
    await db.commit()
    await db.refresh(pb)
    logger.info("playbook_created", agent_id=agent_id, playbook_id=str(pb.id))
    return _to_response(pb)


@router.get("/{agent_id}/playbooks/{playbook_id}", response_model=PlaybookResponse)
async def get_playbook(
    agent_id: str,
    playbook_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Get a specific playbook for an agent."""
    tenant_id = _tenant_id(request)
    await _verify_agent(agent_id, tenant_id, db)

    result = await db.execute(
        select(AgentPlaybook).where(
            AgentPlaybook.id == uuid.UUID(playbook_id),
            AgentPlaybook.agent_id == uuid.UUID(agent_id),
        )
    )
    pb = result.scalar_one_or_none()
    if not pb:
        raise HTTPException(status_code=404, detail="Playbook not found.")
    return _to_response(pb)


@router.put("/{agent_id}/playbooks/{playbook_id}", response_model=PlaybookResponse)
async def update_playbook(
    agent_id: str,
    playbook_id: str,
    body: PlaybookUpsert,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Update a specific playbook for an agent."""
    tenant_id = _tenant_id(request)
    agent = await _verify_agent(agent_id, tenant_id, db)

    result = await db.execute(
        select(AgentPlaybook).where(
            AgentPlaybook.id == uuid.UUID(playbook_id),
            AgentPlaybook.agent_id == agent.id,
        )
    )
    pb = result.scalar_one_or_none()
    if not pb:
        raise HTTPException(status_code=404, detail="Playbook not found.")

    if body.is_default and not pb.is_default:
        existing_defaults = await db.execute(
            select(AgentPlaybook).where(
                AgentPlaybook.agent_id == agent.id,
                AgentPlaybook.is_default.is_(True),
            )
        )
        for existing in existing_defaults.scalars().all():
            existing.is_default = False

    pb.name = body.name
    pb.description = body.description
    pb.intent_triggers = body.intent_triggers
    pb.is_default = body.is_default
    pb.is_active = body.is_active

    pb.config = copy.deepcopy(body.config) if body.config else {}

    await db.commit()
    await db.refresh(pb)
    logger.info("playbook_updated", agent_id=agent_id, playbook_id=playbook_id)
    return _to_response(pb)


@router.delete("/{agent_id}/playbooks/{playbook_id}", status_code=204)
async def delete_playbook(
    agent_id: str,
    playbook_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Delete a specific playbook for an agent."""
    tenant_id = _tenant_id(request)
    await _verify_agent(agent_id, tenant_id, db)

    result = await db.execute(
        select(AgentPlaybook).where(
            AgentPlaybook.id == uuid.UUID(playbook_id),
            AgentPlaybook.agent_id == uuid.UUID(agent_id),
        )
    )
    pb = result.scalar_one_or_none()
    if pb:
        await db.delete(pb)
        await db.commit()
        logger.info("playbook_deleted", agent_id=agent_id, playbook_id=playbook_id)


@router.post("/{agent_id}/playbooks/{playbook_id}/set-default", response_model=PlaybookResponse)
async def set_default_playbook(
    agent_id: str,
    playbook_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Set a playbook as the default, unsetting any other defaults."""
    tenant_id = _tenant_id(request)
    agent = await _verify_agent(agent_id, tenant_id, db)

    all_pbs = await db.execute(
        select(AgentPlaybook).where(
            AgentPlaybook.agent_id == agent.id,
            AgentPlaybook.is_default.is_(True),
        )
    )
    for existing in all_pbs.scalars().all():
        existing.is_default = False

    result = await db.execute(
        select(AgentPlaybook).where(
            AgentPlaybook.id == uuid.UUID(playbook_id),
            AgentPlaybook.agent_id == agent.id,
        )
    )
    pb = result.scalar_one_or_none()
    if not pb:
        raise HTTPException(status_code=404, detail="Playbook not found.")

    pb.is_default = True
    await db.commit()
    await db.refresh(pb)
    logger.info("playbook_set_default", agent_id=agent_id, playbook_id=playbook_id)
    return _to_response(pb)


@router.post("/validate-safety")
async def validate_playbook_safety(
    body: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Validate that playbook text content is safe (no blocked keywords or PII)."""
    from app.services.moderation_service import ModerationService
    
    text = body.get("text", "")
    if not text:
        return {"valid": True, "issues": []}
    
    moderation_service = getattr(request.app.state, "moderation_service", None)
    if not moderation_service:
        moderation_service = ModerationService()
    
    try:
        result = await moderation_service.check_input(text)
        issues = []
        if result.flagged:
            issues = result.categories or []
        return {
            "valid": not result.flagged,
            "issues": issues
        }
    except Exception as e:
        logger.warning("playbook_safety_validation_error", error=str(e))
        return {"valid": True, "issues": []}
