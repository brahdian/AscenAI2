from __future__ import annotations

import copy
import uuid
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.agent import Agent, AgentPlaybook, AgentPlaybookHistory
from app.schemas.chat import PlaybookResponse, PlaybookUpsert, PlaybookHistoryResponse
from shared.orchestration.moderation_service import ModerationService
import shared.pii as pii_service

logger = structlog.get_logger(__name__)
router = APIRouter()

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


def _to_response(pb: AgentPlaybook) -> PlaybookResponse:
    config = pb.config or {}
    return PlaybookResponse(
        id=str(pb.id),
        agent_id=str(pb.agent_id),
        tenant_id=str(pb.tenant_id),
        name=pb.name,
        description=pb.description,
        intent_triggers=pb.intent_triggers or [],
        instructions=config.get("instructions"),
        tone=config.get("tone", "professional"),
        dos=config.get("dos", []),
        donts=config.get("donts", []),
        scenarios=config.get("scenarios", []),
        out_of_scope_response=config.get("out_of_scope_response"),
        fallback_response=config.get("fallback_response"),
        custom_escalation_message=config.get("custom_escalation_message"),
        config=config,
        is_active=pb.is_active,
        created_at=pb.created_at.isoformat() if pb.created_at else "",
        updated_at=pb.updated_at.isoformat() if pb.updated_at else "",
    )


async def _harden_playbook_config(config: dict, request: Request) -> dict:
    """
    Apply safety validation and PII redaction to user-controlled fields.
    
    Raises 422 if moderation flags malicious content.
    """
    moderation_service = getattr(request.app.state, "moderation_service", None)
    if not moderation_service:
        moderation_service = ModerationService()
    
    # 1. Collect all sensitive text for moderation
    text_to_check = []
    if config.get("instructions"):
        text_to_check.append(config["instructions"])
    if config.get("greeting_message"):
        text_to_check.append(config["greeting_message"])
    for s in config.get("scenarios", []):
        text_to_check.append(f"{s.get('trigger', '')} {s.get('response', '')}")
    if config.get("out_of_scope_response"):
        text_to_check.append(config["out_of_scope_response"])
    if config.get("fallback_response"):
        text_to_check.append(config["fallback_response"])
    if config.get("custom_escalation_message"):
        text_to_check.append(config["custom_escalation_message"])
    
    combined_text = " ".join(text_to_check)
    
    # 2. Safety Check (Server-Side Enforcement)
    if combined_text:
        result = await moderation_service.check_input(combined_text)
        if result.flagged:
            logger.warning("playbook_safety_violation", categories=result.categories)
            raise HTTPException(
                status_code=422, 
                detail=f"Playbook content violates safety policy: {', '.join(result.categories or [])}"
            )

    # 3. PII Redaction
    hardened = copy.deepcopy(config)
    
    def _redact(val):
        if not isinstance(val, str):
            return val
        # Standardize on Presidio-based redaction for playbooks
        return pii_service.redact(val)

    if hardened.get("instructions"):
        hardened["instructions"] = _redact(hardened["instructions"])
    if hardened.get("greeting_message"):
        hardened["greeting_message"] = _redact(hardened["greeting_message"])
    
    if hardened.get("scenarios"):
        for s in hardened["scenarios"]:
            if s.get("trigger"):
                s["trigger"] = _redact(s["trigger"])
            if s.get("response"):
                s["response"] = _redact(s["response"])
                
    if hardened.get("out_of_scope_response"):
        hardened["out_of_scope_response"] = _redact(hardened["out_of_scope_response"])
    if hardened.get("fallback_response"):
        hardened["fallback_response"] = _redact(hardened["fallback_response"])
    if hardened.get("custom_escalation_message"):
        hardened["custom_escalation_message"] = _redact(hardened["custom_escalation_message"])

    return hardened


def _get_config_diff(old: dict, new: dict) -> dict:
    """Calculate shallow diff for logging."""
    diff = {}
    all_keys = set(old.keys()) | set(new.keys())
    for k in all_keys:
        v_old = old.get(k)
        v_new = new.get(k)
        if v_old != v_new:
            diff[k] = {"from": v_old, "to": v_new}
    return diff


async def _verify_agent(agent_id: str, tenant_id: str, request: Request, db: AsyncSession) -> Agent:
    query = select(Agent).where(
        Agent.id == uuid.UUID(agent_id),
        Agent.tenant_id == uuid.UUID(tenant_id),
    )
    
    # Apply isolation (CRIT-005)
    raid = _restricted_agent_id(request)
    if raid:
        if uuid.UUID(agent_id) != raid:
             raise HTTPException(status_code=404, detail="Agent not found.")
        query = query.where(Agent.id == raid)

    result = await db.execute(query)
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
    await _verify_agent(agent_id, tenant_id, request, db)

    result = await db.execute(
        select(AgentPlaybook)
        .where(AgentPlaybook.agent_id == uuid.UUID(agent_id))
        .order_by(AgentPlaybook.created_at.asc())
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
    agent = await _verify_agent(agent_id, tenant_id, request, db)


    incoming = await _harden_playbook_config(body.config or {}, request)
    if not incoming:
        incoming = {"tone": "professional", "dos": [], "donts": [], "scenarios": []}

    pb = AgentPlaybook(
        agent_id=agent.id,
        tenant_id=agent.tenant_id,
        name=body.name,
        description=body.description,
        intent_triggers=body.intent_triggers,
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
    await _verify_agent(agent_id, tenant_id, request, db)

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
    agent = await _verify_agent(agent_id, tenant_id, request, db)

    result = await db.execute(
        select(AgentPlaybook).where(
            AgentPlaybook.id == uuid.UUID(playbook_id),
            AgentPlaybook.agent_id == agent.id,
        )
    )
    pb = result.scalar_one_or_none()
    if not pb:
        raise HTTPException(status_code=404, detail="Playbook not found.")


    pb.name = body.name
    pb.description = body.description
    pb.intent_triggers = body.intent_triggers
    pb.is_active = body.is_active

    old_config = copy.deepcopy(pb.config or {})
    new_config = await _harden_playbook_config(body.config or {}, request)
    
    # Snapshot current state before applying updates
    history_entry = AgentPlaybookHistory(
        playbook_id=pb.id,
        tenant_id=pb.tenant_id,
        agent_id=pb.agent_id,
        name=pb.name,
        description=pb.description,
        intent_triggers=pb.intent_triggers,
        config=old_config,
        snapshot_reason="update_via_api"
    )
    db.add(history_entry)
    
    pb.config = new_config

    await db.commit()
    await db.refresh(pb)

    diff = _get_config_diff(old_config, new_config)
    logger.info(
        "playbook_updated", 
        agent_id=agent_id, 
        playbook_id=playbook_id,
        config_diff=diff
    )
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
    await _verify_agent(agent_id, tenant_id, request, db)

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


@router.get("/{agent_id}/playbooks/{playbook_id}/history", response_model=list[PlaybookHistoryResponse])
async def list_playbook_history(
    agent_id: str,
    playbook_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """List historical configurations for a playbook."""
    tenant_id = _tenant_id(request)
    await _verify_agent(agent_id, tenant_id, request, db)

    result = await db.execute(
        select(AgentPlaybookHistory).where(
            AgentPlaybookHistory.playbook_id == uuid.UUID(playbook_id),
            AgentPlaybookHistory.agent_id == uuid.UUID(agent_id),
        ).order_by(AgentPlaybookHistory.created_at.desc())
    )
    history = result.scalars().all()
    return [h.to_dict() for h in history]


@router.post("/validate-safety")
async def validate_playbook_safety(
    body: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Validate that playbook text content is safe (no blocked keywords or PII)."""
    from shared.orchestration.moderation_service import ModerationService
    
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
