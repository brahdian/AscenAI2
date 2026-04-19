from __future__ import annotations

import copy
import uuid
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_tenant_db, get_current_tenant
from app.core.redis_client import get_redis
from app.models.agent import Agent, AgentGuardrails, AgentGuardrailChangeRequest
from app.models.agent_custom_guardrail import AgentCustomGuardrail
from app.schemas.chat import (
    GuardrailsUpsert,
    GuardrailsResponse,
    CustomGuardrailSchema,
    CustomGuardrailCreate,
    CustomGuardrailUpdate,
)

logger = structlog.get_logger(__name__)
router = APIRouter()


def _gr_to_response(gr: AgentGuardrails) -> GuardrailsResponse:
    cfg = gr.config or {}
    return GuardrailsResponse(
        id=str(gr.id),
        agent_id=str(gr.agent_id),
        tenant_id=str(gr.tenant_id),
        config=cfg,
        is_active=gr.is_active,
        created_at=gr.created_at.isoformat(),
        updated_at=gr.updated_at.isoformat(),
    )


async def _invalidate_guardrails_cache(agent_id: str, is_custom: bool = False):
    """Clear the Redis cache for this agent's guardrails."""
    try:
        redis = await get_redis()
        key = f"custom_guardrails:{agent_id}" if is_custom else f"agent_guardrails:{agent_id}"
        await redis.delete(key)
    except Exception as e:
        logger.warning("cache_invalidation_failed", agent_id=agent_id, error=str(e))


def _custom_to_response(c: AgentCustomGuardrail) -> CustomGuardrailSchema:
    return CustomGuardrailSchema(
        id=str(c.id),
        agent_id=str(c.agent_id),
        tenant_id=str(c.tenant_id),
        rule=c.rule,
        category=c.category,
        is_active=c.is_active,
        created_at=c.created_at.isoformat(),
        updated_at=c.updated_at.isoformat(),
    )


def _restricted_agent_id(request: Request) -> uuid.UUID | None:
    """Extract optional agent restriction passed by the API Gateway proxy."""
    raid = request.headers.get("X-Restricted-Agent-ID")
    if raid:
        try:
            return uuid.UUID(raid)
        except ValueError:
            return None
    return None


async def _get_agent(agent_id: str, tenant_id: str, db: AsyncSession, request: Request | None = None) -> Agent:
    # Apply isolation (CRIT-005)
    if request:
        raid = _restricted_agent_id(request)
        if raid and uuid.UUID(agent_id) != raid:
            raise HTTPException(status_code=404, detail="Agent not found.")

    result = await db.execute(
        select(Agent).where(
            Agent.id == uuid.UUID(agent_id),
            Agent.tenant_id == uuid.UUID(tenant_id),
        )
    )
    agent_obj = result.scalar_one_or_none()
    if not agent_obj:
        raise HTTPException(status_code=404, detail="Agent not found.")
    return agent_obj


@router.get("/{agent_id}/guardrails", response_model=GuardrailsResponse)
async def get_guardrails(
    agent_id: str,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
    tenant=Depends(get_current_tenant),
):
    """Get the guardrails config for an agent."""
    tenant_id = str(tenant)
    await _get_agent(agent_id, tenant_id, db, request=request)

    result = await db.execute(
        select(AgentGuardrails).where(AgentGuardrails.agent_id == uuid.UUID(agent_id))
    )
    gr = result.scalar_one_or_none()
    if not gr:
        raise HTTPException(status_code=404, detail="Guardrails not configured for this agent.")
    return _gr_to_response(gr)


@router.put("/{agent_id}/guardrails", response_model=GuardrailsResponse)
async def upsert_guardrails(
    agent_id: str,
    body: GuardrailsUpsert,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
    tenant=Depends(get_current_tenant),
):
    """Create or update guardrails for an agent."""
    tenant_id = str(tenant)
    await _get_agent(agent_id, tenant_id, db, request=request)

    result = await db.execute(
        select(AgentGuardrails).where(AgentGuardrails.agent_id == uuid.UUID(agent_id))
    )
    gr = result.scalar_one_or_none()

    if gr is None:
        gr = AgentGuardrails(
            agent_id=uuid.UUID(agent_id),
            tenant_id=uuid.UUID(tenant_id),
            config={},
        )
        db.add(gr)

    ALLOWED_CONFIG_KEYS = {
        "content_filter_level", "blocked_keywords", "blocked_topics",
        "allowed_topics", "profanity_filter", "pii_redaction",
        "max_response_length", "require_disclaimer", "blocked_message",
        "off_topic_message", "pii_pseudonymization"
    }

    incoming_config = body.config or {}
    current_config = copy.deepcopy(gr.config) if gr.config else {}

    # ONLY allow explicitly listed keys to prevent JSON injection
    for key, value in incoming_config.items():
        if key not in ALLOWED_CONFIG_KEYS:
            continue
        
        if isinstance(value, dict) and key in current_config and isinstance(current_config[key], dict):
            current_config[key] = {**current_config[key], **value}
        else:
            current_config[key] = value

    gr.config = current_config
    gr.is_active = body.is_active

    await db.commit()
    await db.refresh(gr)
    await _invalidate_guardrails_cache(agent_id)
    logger.info("guardrails_upserted", agent_id=agent_id, tenant_id=tenant_id)
    return _gr_to_response(gr)


@router.delete("/{agent_id}/guardrails", status_code=204)
async def delete_guardrails(
    agent_id: str,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
    tenant=Depends(get_current_tenant),
):
    """Remove guardrails for an agent."""
    tenant_id = str(tenant)
    await _get_agent(agent_id, tenant_id, db, request=request)

    result = await db.execute(
        select(AgentGuardrails).where(AgentGuardrails.agent_id == uuid.UUID(agent_id))
    )
    gr = result.scalar_one_or_none()
    if gr:
        await db.delete(gr)
        await db.commit()
        await _invalidate_guardrails_cache(agent_id)


@router.get("/{agent_id}/guardrails/custom", response_model=list[CustomGuardrailSchema])
async def list_custom_guardrails(
    agent_id: str,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db)
):
    """List custom guardrails for an agent."""
    await _get_agent(agent_id, str(tenant_id), db, request=request)
    result = await db.execute(
        select(AgentCustomGuardrail).where(AgentCustomGuardrail.agent_id == uuid.UUID(agent_id))
    )
    items = result.scalars().all()
    return [_custom_to_response(i) for i in items]


@router.post("/{agent_id}/guardrails/custom", response_model=CustomGuardrailSchema)
async def create_custom_guardrail(
    agent_id: str,
    body: CustomGuardrailCreate,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db)
):
    """Add a new custom guardrail rule."""
    await _get_agent(agent_id, str(tenant_id), db, request=request)
    item = AgentCustomGuardrail(
        agent_id=uuid.UUID(agent_id),
        tenant_id=uuid.UUID(tenant_id),
        rule=body.rule,
        category=body.category,
        is_active=body.is_active
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    await _invalidate_guardrails_cache(agent_id, is_custom=True)
    return _custom_to_response(item)


@router.patch("/{agent_id}/guardrails/custom/{custom_id}", response_model=CustomGuardrailSchema)
async def update_custom_guardrail(
    agent_id: str,
    custom_id: str,
    body: CustomGuardrailUpdate,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db)
):
    """Update a custom guardrail rule."""
    await _get_agent(agent_id, str(tenant_id), db, request=request)
    result = await db.execute(
        select(AgentCustomGuardrail).where(
            AgentCustomGuardrail.id == uuid.UUID(custom_id),
            AgentCustomGuardrail.agent_id == uuid.UUID(agent_id)
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Custom guardrail not found.")

    if body.rule is not None:
        item.rule = body.rule
    if body.category is not None:
        item.category = body.category
    if body.is_active is not None:
        item.is_active = body.is_active

    await db.commit()
    await db.refresh(item)
    await _invalidate_guardrails_cache(agent_id, is_custom=True)
    return _custom_to_response(item)


@router.delete("/{agent_id}/guardrails/custom/{custom_id}", status_code=204)
async def delete_custom_guardrail(
    agent_id: str,
    custom_id: str,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db)
):
    """Delete a custom guardrail rule."""
    await _get_agent(agent_id, str(tenant_id), db, request=request)
    result = await db.execute(
        select(AgentCustomGuardrail).where(
            AgentCustomGuardrail.id == uuid.UUID(custom_id),
            AgentCustomGuardrail.agent_id == uuid.UUID(agent_id)
        )
    )
    item = result.scalar_one_or_none()
    if item:
        await db.delete(item)
        await db.commit()
        await _invalidate_guardrails_cache(agent_id, is_custom=True)


# Global guardrail change requests (platform-level)
class GuardrailChangeRequestCreate(BaseModel):
    guardrail_id: str
    proposed_rule: str
    reason: str


class GuardrailChangeRequest(BaseModel):
    id: str
    guardrail_id: str
    proposed_rule: str
    reason: str
    status: str = "pending"
    created_at: str


@router.post("/change-requests", response_model=GuardrailChangeRequest)
async def create_guardrail_change_request(
    body: GuardrailChangeRequestCreate,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
    tenant=Depends(get_current_tenant),
):
    """Submit a request to change a global guardrail rule."""
    tenant_id = str(tenant)
    change_request = AgentGuardrailChangeRequest(
        tenant_id=uuid.UUID(tenant_id),
        guardrail_id=body.guardrail_id,
        proposed_rule=body.proposed_rule,
        reason=body.reason,
        status="pending"
    )
    db.add(change_request)
    await db.commit()
    await db.refresh(change_request)
    
    logger.info("guardrail_change_request_created", guardrail_id=body.guardrail_id, tenant_id=tenant_id, request_id=str(change_request.id))
    
    return GuardrailChangeRequest(
        id=str(change_request.id),
        guardrail_id=change_request.guardrail_id,
        proposed_rule=change_request.proposed_rule,
        reason=change_request.reason,
        status=change_request.status,
        created_at=change_request.created_at.isoformat()
    )


@router.get("/change-requests", response_model=list[GuardrailChangeRequest])
async def list_guardrail_change_requests(
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
    tenant=Depends(get_current_tenant),
):
    """List all guardrail change requests for this tenant."""
    tenant_id = str(tenant)
    result = await db.execute(
        select(AgentGuardrailChangeRequest).where(
            AgentGuardrailChangeRequest.tenant_id == uuid.UUID(tenant_id)
        ).order_by(AgentGuardrailChangeRequest.created_at.desc())
    )
    items = result.scalars().all()
    
    return [
        GuardrailChangeRequest(
            id=str(i.id),
            guardrail_id=i.guardrail_id,
            proposed_rule=i.proposed_rule,
            reason=i.reason,
            status=i.status,
            created_at=i.created_at.isoformat()
        ) for i in items
    ]
