from __future__ import annotations

import uuid
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_tenant
from app.models.agent import Agent, AgentGuardrails
from app.schemas.chat import GuardrailsUpsert, GuardrailsResponse

logger = structlog.get_logger(__name__)
router = APIRouter()


def _gr_to_response(gr: AgentGuardrails) -> GuardrailsResponse:
    return GuardrailsResponse(
        id=str(gr.id),
        agent_id=str(gr.agent_id),
        tenant_id=str(gr.tenant_id),
        blocked_keywords=gr.blocked_keywords or [],
        blocked_topics=gr.blocked_topics or [],
        allowed_topics=gr.allowed_topics or [],
        profanity_filter=gr.profanity_filter,
        pii_redaction=gr.pii_redaction,
        max_response_length=gr.max_response_length,
        require_disclaimer=gr.require_disclaimer,
        blocked_message=gr.blocked_message,
        off_topic_message=gr.off_topic_message,
        content_filter_level=gr.content_filter_level,
        is_active=gr.is_active,
        created_at=gr.created_at.isoformat(),
        updated_at=gr.updated_at.isoformat(),
    )


async def _get_agent(agent_id: str, tenant_id: str, db: AsyncSession) -> Agent:
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


@router.get("/{agent_id}/guardrails", response_model=GuardrailsResponse)
async def get_guardrails(
    agent_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    tenant=Depends(get_current_tenant),
):
    """Get the guardrails config for an agent."""
    tenant_id = str(tenant.id)
    await _get_agent(agent_id, tenant_id, db)

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
    db: AsyncSession = Depends(get_db),
    tenant=Depends(get_current_tenant),
):
    """Create or update guardrails for an agent."""
    tenant_id = str(tenant.id)
    await _get_agent(agent_id, tenant_id, db)

    result = await db.execute(
        select(AgentGuardrails).where(AgentGuardrails.agent_id == uuid.UUID(agent_id))
    )
    gr = result.scalar_one_or_none()

    if gr is None:
        gr = AgentGuardrails(
            agent_id=uuid.UUID(agent_id),
            tenant_id=uuid.UUID(tenant_id),
        )
        db.add(gr)

    gr.blocked_keywords = body.blocked_keywords
    gr.blocked_topics = body.blocked_topics
    gr.allowed_topics = body.allowed_topics
    gr.profanity_filter = body.profanity_filter
    gr.pii_redaction = body.pii_redaction
    gr.max_response_length = body.max_response_length
    gr.require_disclaimer = body.require_disclaimer
    gr.blocked_message = body.blocked_message
    gr.off_topic_message = body.off_topic_message
    gr.content_filter_level = body.content_filter_level
    gr.is_active = body.is_active

    await db.commit()
    await db.refresh(gr)
    logger.info("guardrails_upserted", agent_id=agent_id, tenant_id=tenant_id)
    return _gr_to_response(gr)


@router.delete("/{agent_id}/guardrails", status_code=204)
async def delete_guardrails(
    agent_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    tenant=Depends(get_current_tenant),
):
    """Remove guardrails for an agent."""
    tenant_id = str(tenant.id)
    await _get_agent(agent_id, tenant_id, db)

    result = await db.execute(
        select(AgentGuardrails).where(AgentGuardrails.agent_id == uuid.UUID(agent_id))
    )
    gr = result.scalar_one_or_none()
    if gr:
        await db.delete(gr)
        await db.commit()
