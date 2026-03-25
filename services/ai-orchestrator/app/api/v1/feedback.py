from __future__ import annotations

import csv
import io
import json
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.agent import Agent, Message, MessageFeedback, Session as AgentSession
from app.schemas.chat import FeedbackCreate, FeedbackResponse, FeedbackSummary

logger = structlog.get_logger(__name__)
router = APIRouter()


def _tenant_id(request: Request) -> str:
    tid = request.headers.get("X-Tenant-ID") or getattr(request.state, "tenant_id", None)
    if not tid:
        raise HTTPException(status_code=401, detail="Tenant ID required.")
    return tid


CORRECTIONS_KEY = "corrections:{agent_id}"
CORRECTIONS_MAX = 20  # keep the most recent N per agent


def _fb_to_response(fb: MessageFeedback) -> FeedbackResponse:
    return FeedbackResponse(
        id=str(fb.id),
        message_id=str(fb.message_id),
        session_id=fb.session_id,
        tenant_id=str(fb.tenant_id),
        agent_id=str(fb.agent_id),
        rating=fb.rating,
        labels=fb.labels or [],
        comment=fb.comment,
        ideal_response=fb.ideal_response,
        correction_reason=fb.correction_reason,
        feedback_source=fb.feedback_source,
        created_at=fb.created_at.isoformat() if fb.created_at else "",
    )


async def _store_correction_in_redis(
    request: Request,
    agent_id: str,
    user_message_content: str,
    ideal_response: str,
) -> None:
    """
    Push an operator correction into Redis so the orchestrator can inject it
    as a few-shot example on future turns for this agent.
    """
    import json, time
    redis = getattr(request.app.state, "redis", None)
    if redis is None:
        return
    key = CORRECTIONS_KEY.format(agent_id=agent_id)
    entry = json.dumps({
        "user_message": user_message_content[:300],
        "ideal_response": ideal_response[:800],
        "ts": time.time(),
    })
    pipe = redis.pipeline()
    pipe.lpush(key, entry)
    pipe.ltrim(key, 0, CORRECTIONS_MAX - 1)
    pipe.expire(key, 60 * 60 * 24 * 30)  # 30-day TTL
    await pipe.execute()


@router.post("", response_model=FeedbackResponse, status_code=201)
async def submit_feedback(
    body: FeedbackCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Submit a thumbs-up/down rating with optional labels on an assistant message."""
    tenant_id = _tenant_id(request)

    if body.rating not in ("positive", "negative"):
        raise HTTPException(status_code=422, detail="rating must be 'positive' or 'negative'")

    # Verify message belongs to this tenant
    msg_result = await db.execute(
        select(Message).where(
            Message.id == uuid.UUID(body.message_id),
            Message.tenant_id == uuid.UUID(tenant_id),
        )
    )
    msg = msg_result.scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found.")

    fb = MessageFeedback(
        message_id=uuid.UUID(body.message_id),
        session_id=body.session_id,
        tenant_id=uuid.UUID(tenant_id),
        agent_id=uuid.UUID(body.agent_id),
        rating=body.rating,
        labels=body.labels or [],
        comment=body.comment,
        ideal_response=body.ideal_response,
        correction_reason=body.correction_reason,
        feedback_source=body.feedback_source or "user",
    )
    db.add(fb)
    await db.commit()
    await db.refresh(fb)
    logger.info("feedback_submitted", tenant_id=tenant_id, rating=body.rating,
                has_correction=bool(body.ideal_response))

    # If an ideal response was provided, push a correction into Redis so
    # the orchestrator injects it as a few-shot example on future turns.
    if body.ideal_response and msg:
        await _store_correction_in_redis(
            request=request,
            agent_id=body.agent_id,
            user_message_content=msg.content,
            ideal_response=body.ideal_response,
        )

    return _fb_to_response(fb)


@router.get("", response_model=list[FeedbackResponse])
async def list_feedback(
    request: Request,
    agent_id: Optional[str] = Query(None),
    rating: Optional[str] = Query(None, description="positive or negative"),
    session_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List feedback submissions for the tenant with optional filters."""
    tenant_id = _tenant_id(request)

    query = (
        select(MessageFeedback)
        .where(MessageFeedback.tenant_id == uuid.UUID(tenant_id))
        .order_by(MessageFeedback.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    if agent_id:
        query = query.where(MessageFeedback.agent_id == uuid.UUID(agent_id))
    if rating:
        query = query.where(MessageFeedback.rating == rating)
    if session_id:
        query = query.where(MessageFeedback.session_id == session_id)

    result = await db.execute(query)
    return [_fb_to_response(fb) for fb in result.scalars().all()]


@router.get("/summary", response_model=FeedbackSummary)
async def feedback_summary(
    request: Request,
    agent_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Aggregate feedback stats: positive %, top labels, per-agent breakdown."""
    tenant_id = _tenant_id(request)

    query = select(MessageFeedback).where(
        MessageFeedback.tenant_id == uuid.UUID(tenant_id)
    )
    if agent_id:
        query = query.where(MessageFeedback.agent_id == uuid.UUID(agent_id))

    result = await db.execute(query)
    all_fb = result.scalars().all()

    total = len(all_fb)
    positive = sum(1 for f in all_fb if f.rating == "positive")
    negative = total - positive
    positive_pct = round(positive / total * 100, 1) if total else 0.0

    pos_labels: Counter = Counter()
    neg_labels: Counter = Counter()
    by_agent: dict[str, dict] = {}

    for fb in all_fb:
        labels = fb.labels or []
        if fb.rating == "positive":
            pos_labels.update(labels)
        else:
            neg_labels.update(labels)

        aid = str(fb.agent_id)
        if aid not in by_agent:
            by_agent[aid] = {"agent_id": aid, "positive": 0, "negative": 0, "total": 0}
        by_agent[aid][fb.rating] += 1
        by_agent[aid]["total"] += 1

    # Enrich agent breakdown with names
    agents_result = await db.execute(
        select(Agent).where(Agent.tenant_id == uuid.UUID(tenant_id))
    )
    agent_names = {str(a.id): a.name for a in agents_result.scalars().all()}
    for entry in by_agent.values():
        entry["agent_name"] = agent_names.get(entry["agent_id"], "Unknown")
        entry["positive_pct"] = round(
            entry["positive"] / entry["total"] * 100, 1
        ) if entry["total"] else 0.0

    return FeedbackSummary(
        total=total,
        positive=positive,
        negative=negative,
        positive_pct=positive_pct,
        top_positive_labels=[{"label": l, "count": c} for l, c in pos_labels.most_common(10)],
        top_negative_labels=[{"label": l, "count": c} for l, c in neg_labels.most_common(10)],
        by_agent=list(by_agent.values()),
    )


@router.get("/export")
async def export_feedback(
    request: Request,
    format: str = Query("jsonl", description="jsonl or csv"),
    agent_id: Optional[str] = Query(None),
    rating: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """
    Export labelled feedback as JSONL (for fine-tuning) or CSV (for review).
    JSONL format: one JSON object per line with message content + rating + labels.
    """
    tenant_id = _tenant_id(request)

    query = (
        select(MessageFeedback, Message)
        .join(Message, Message.id == MessageFeedback.message_id)
        .where(MessageFeedback.tenant_id == uuid.UUID(tenant_id))
        .order_by(MessageFeedback.created_at.desc())
    )
    if agent_id:
        query = query.where(MessageFeedback.agent_id == uuid.UUID(agent_id))
    if rating:
        query = query.where(MessageFeedback.rating == rating)

    result = await db.execute(query)
    rows = result.all()

    if format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["feedback_id", "message_id", "session_id", "agent_id",
                         "rating", "labels", "comment", "message_content", "created_at"])
        for fb, msg in rows:
            writer.writerow([
                str(fb.id), str(fb.message_id), fb.session_id, str(fb.agent_id),
                fb.rating, "|".join(fb.labels or []), fb.comment or "",
                msg.content[:500], fb.created_at.isoformat() if fb.created_at else "",
            ])
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=feedback_export.csv"},
        )
    else:
        lines = []
        for fb, msg in rows:
            lines.append(json.dumps({
                "feedback_id": str(fb.id),
                "message_id": str(fb.message_id),
                "session_id": fb.session_id,
                "agent_id": str(fb.agent_id),
                "rating": fb.rating,
                "labels": fb.labels or [],
                "comment": fb.comment,
                "message_content": msg.content,
                "message_role": msg.role,
                "created_at": fb.created_at.isoformat() if fb.created_at else "",
            }, ensure_ascii=False))
        content = "\n".join(lines)
        return StreamingResponse(
            iter([content]),
            media_type="application/x-ndjson",
            headers={"Content-Disposition": "attachment; filename=feedback_export.jsonl"},
        )
