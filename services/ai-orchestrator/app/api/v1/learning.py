from __future__ import annotations

import uuid
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy import select, and_
from sqlalchemy.orm import aliased
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_tenant_db
from app.core.security import get_current_tenant
from app.models.agent import Agent, Session, Message, MessageFeedback
from app.schemas.chat import (
    LearningInsights, LearningGap, UnreviewedNegative,
    GuardrailTrigger, SuggestedTrainingPair,
)
from app.services import pii_service

logger = structlog.get_logger(__name__)
router = APIRouter()


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
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found.")
    return agent


@router.get("/{agent_id}/learning", response_model=LearningInsights)
async def get_learning_insights(
    agent_id: str,
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_tenant_db),
    tenant=Depends(get_current_tenant),
):
    """
    Return actionable learning insights for an agent:
    - knowledge_gaps: user messages that triggered fallback responses
    - unreviewed_negatives: negative feedback without an ideal response correction
    - guardrail_triggers: user messages blocked by guardrails
    - suggested_training_pairs: positively-rated messages worth formalizing
    """
    tenant_id = str(tenant)
    agent_uuid = uuid.UUID(agent_id)
    await _get_agent(agent_id, tenant_id, db, request=request)

    # 1. Knowledge gaps: assistant messages with is_fallback=True for this agent.
    # Use a self-join to fetch the preceding user message in the same query,
    # avoiding an N+1 pattern.
    UserMsg = aliased(Message)
    fallback_result = await db.execute(
        select(Message, UserMsg)
        .join(
            UserMsg,
            and_(
                UserMsg.session_id == Message.session_id,
                UserMsg.role == "user",
                UserMsg.created_at < Message.created_at,
            ),
        )
        .where(
            and_(
                Message.tenant_id == uuid.UUID(tenant_id),
                Message.is_fallback.is_(True),
                Message.role == "assistant",
                # Filter to sessions that belong to this specific agent
                Message.session_id.in_(
                    select(Session.id).where(
                        and_(
                            Session.agent_id == agent_uuid,
                            Session.tenant_id == uuid.UUID(tenant_id),
                        )
                    )
                ),
            )
        )
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    rows = fallback_result.all()

    knowledge_gaps: list[LearningGap] = []
    for asst_msg, user_msg in rows:
        knowledge_gaps.append(LearningGap(
            message_id=str(asst_msg.id),
            session_id=asst_msg.session_id,
            agent_id=agent_id,
            user_message=pii_service.redact_for_display(user_msg.content[:500], None),
            agent_response=pii_service.redact_for_display(asst_msg.content[:500], None),
            created_at=asst_msg.created_at.isoformat(),
        ))

    # 2. Unreviewed negatives: negative feedback without ideal_response
    neg_result = await db.execute(
        select(MessageFeedback).where(
            and_(
                MessageFeedback.agent_id == agent_uuid,
                MessageFeedback.rating == "negative",
                MessageFeedback.ideal_response.is_(None),
            )
        ).order_by(MessageFeedback.created_at.desc()).limit(limit)
    )
    neg_feedbacks = neg_result.scalars().all()

    unreviewed_negatives: list[UnreviewedNegative] = []
    for fb in neg_feedbacks:
        msg_result = await db.execute(
            select(Message).where(Message.id == fb.message_id)
        )
        msg = msg_result.scalar_one_or_none()
        if msg:
            unreviewed_negatives.append(UnreviewedNegative(
                feedback_id=str(fb.id),
                message_id=str(fb.message_id),
                session_id=fb.session_id,
                agent_id=agent_id,
                agent_response=pii_service.redact_for_display(msg.content[:500], None),
                labels=fb.labels or [],
                comment=pii_service.redact_for_display(fb.comment, None),
                created_at=fb.created_at.isoformat(),
            ))

    # 3. Guardrail triggers: user messages that were blocked
    trigger_result = await db.execute(
        select(Message).where(
            and_(
                Message.tenant_id == uuid.UUID(tenant_id),
                Message.guardrail_triggered.is_not(None),
                Message.role == "user",
                # Hardening: Enforce agent-level isolation for guardrail triggers
                Message.session_id.in_(
                    select(Session.id).where(
                        and_(
                            Session.agent_id == agent_uuid,
                            Session.tenant_id == uuid.UUID(tenant_id),
                        )
                    )
                ),
            )
        ).order_by(Message.created_at.desc()).limit(limit)
    )
    trigger_msgs = trigger_result.scalars().all()

    guardrail_triggers: list[GuardrailTrigger] = []
    for msg in trigger_msgs:
        guardrail_triggers.append(GuardrailTrigger(
            message_id=str(msg.id),
            session_id=msg.session_id,
            agent_id=agent_id,
            user_message=pii_service.redact_for_display(msg.content[:500], None),
            trigger_reason=msg.guardrail_triggered or "",
            created_at=msg.created_at.isoformat(),
        ))

    # 4. Suggested training pairs: positive feedback not yet in corrections
    pos_result = await db.execute(
        select(MessageFeedback).where(
            and_(
                MessageFeedback.agent_id == agent_uuid,
                MessageFeedback.rating == "positive",
                MessageFeedback.ideal_response.is_(None),
            )
        ).order_by(MessageFeedback.created_at.desc()).limit(limit)
    )
    pos_feedbacks = pos_result.scalars().all()

    suggested_pairs: list[SuggestedTrainingPair] = []
    for fb in pos_feedbacks:
        msg_result = await db.execute(
            select(Message).where(Message.id == fb.message_id)
        )
        asst_msg = msg_result.scalar_one_or_none()
        if not asst_msg:
            continue
        user_result = await db.execute(
            select(Message).where(
                and_(
                    Message.session_id == asst_msg.session_id,
                    Message.role == "user",
                    Message.created_at < asst_msg.created_at,
                )
            ).order_by(Message.created_at.desc()).limit(1)
        )
        user_msg = user_result.scalar_one_or_none()
        if user_msg:
            suggested_pairs.append(SuggestedTrainingPair(
                feedback_id=str(fb.id),
                message_id=str(asst_msg.id),
                session_id=asst_msg.session_id,
                agent_id=agent_id,
                user_message=pii_service.redact_for_display(user_msg.content[:500], None),
                agent_response=pii_service.redact_for_display(asst_msg.content[:500], None),
                labels=fb.labels or [],
                created_at=fb.created_at.isoformat(),
            ))

    return LearningInsights(
        agent_id=agent_id,
        knowledge_gaps=knowledge_gaps,
        unreviewed_negatives=unreviewed_negatives,
        guardrail_triggers=guardrail_triggers,
        suggested_training_pairs=suggested_pairs,
        total_gaps=len(knowledge_gaps),
        total_unreviewed=len(unreviewed_negatives),
        total_triggers=len(guardrail_triggers),
    )
