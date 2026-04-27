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
from app.core.security import get_tenant_db
from app.models.agent import Agent, Message, MessageFeedback, Session as AgentSession
from app.schemas.chat import FeedbackCreate, FeedbackResponse, FeedbackSummary
import shared.pii as pii_service

logger = structlog.get_logger(__name__)
router = APIRouter()


def _tenant_id(request: Request) -> str:
    """
    Extract tenant_id stamped by the AuthMiddleware onto request.state.
    SECURITY: We prioritize request.state over the raw header to prevent spoofing.
    """
    tid = getattr(request.state, "tenant_id", None)
    if not tid:
        # Fallback for internal proxy requests from API Gateway
        tid = request.headers.get("X-Tenant-ID")
    if not tid:
        raise HTTPException(status_code=401, detail="Tenant ID required.")
    return tid


def _restricted_agent_id(request: Request) -> uuid.UUID | None:
    """Extract optional agent restriction passed by the API Gateway proxy.
    
    If present, this indicates that the caller (e.g., a Widget Key) is 
    STRICTLY restricted to this specific agent.
    """
    raid = request.headers.get("X-Restricted-Agent-ID")
    if raid:
        try:
            return uuid.UUID(raid)
        except ValueError:
            return None
    return None


CORRECTIONS_KEY = "corrections:{agent_id}"
CORRECTIONS_MAX = 20  # keep the most recent N per agent


def _fb_to_response(fb: MessageFeedback, message_content: dict | None = None) -> FeedbackResponse:
    return FeedbackResponse(
        id=str(fb.id),
        message_id=str(fb.message_id),
        session_id=fb.session_id,
        tenant_id=str(fb.tenant_id),
        agent_id=str(fb.agent_id),
        rating=fb.rating,
        labels=fb.labels or [],
        comment=pii_service.redact_for_display(fb.comment, None),
        ideal_response=pii_service.redact_for_display(fb.ideal_response, None),
        correction_reason=pii_service.redact_for_display(fb.correction_reason, None),
        playbook_correction=fb.playbook_correction,
        tool_corrections=fb.tool_corrections or [],
        feedback_source=fb.feedback_source,
        created_at=fb.created_at.isoformat() if fb.created_at else "",
        agent_response=pii_service.redact_for_display(message_content.get("agent_response"), None) if message_content else None,
        user_message=pii_service.redact_for_display(message_content.get("user_message"), None) if message_content else None,
    )


async def _store_correction_in_redis(
    request: Request,
    agent_id: str,
    user_message_content: str,
    ideal_response: Optional[str],
    playbook_correction: Optional[dict],
    tool_corrections: list[dict],
) -> None:
    """
    Push an operator correction into Redis so the orchestrator injects it
    as a few-shot example on future turns for this agent.

    The entry includes:
      - ideal_response:      corrected text answer
      - playbook_correction: which playbook should have been triggered
      - tool_corrections:    per-tool judgements (wrong tool, correct alternative)
    """
    import json, time
    redis = getattr(request.app.state, "redis", None)
    if redis is None:
        return
    key = CORRECTIONS_KEY.format(agent_id=agent_id)
    entry = json.dumps({
        "user_message": user_message_content[:300],
        "ideal_response": (ideal_response or "")[:800],
        "playbook_correction": playbook_correction,
        "tool_corrections": tool_corrections,
        "ts": time.time(),
    })
    try:
        pipe = redis.pipeline()
        pipe.lpush(key, entry)
        pipe.ltrim(key, 0, CORRECTIONS_MAX - 1)
        pipe.expire(key, 60 * 60 * 24 * 30)  # 30-day TTL
        await pipe.execute()
        logger.info("feedback_correction_cached", agent_id=agent_id, key=key)
    except Exception as e:
        logger.error("feedback_redis_push_failed", error=str(e), agent_id=agent_id)


@router.post("", response_model=FeedbackResponse, status_code=201)
async def submit_feedback(
    body: FeedbackCreate,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
):
    """Submit a thumbs-up/down rating with optional labels on an assistant message."""
    tenant_id = _tenant_id(request)

    if body.rating not in ("positive", "negative"):
        raise HTTPException(status_code=422, detail="rating must be 'positive' or 'negative'")

    # Apply deep isolation restriction if present (CRIT-005)
    raid = _restricted_agent_id(request)
    if raid:
        if uuid.UUID(body.agent_id) != raid:
            raise HTTPException(status_code=403, detail="Access denied to this agent.")

    msg_result = await db.execute(
        select(Message).where(
            Message.id == uuid.UUID(body.message_id),
            Message.tenant_id == uuid.UUID(tenant_id),
        )
    )
    msg = msg_result.scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found.")
    
    # Verify message agent matches restricted agent if present
    if raid and msg.agent_id != raid:
        raise HTTPException(status_code=404, detail="Message not found.")

    tool_corrections_raw = [tc.model_dump() for tc in (body.tool_corrections or [])]

    ideal_response_redacted = None
    if body.ideal_response:
        ideal_response_redacted = pii_service.redact(body.ideal_response)

    fb = MessageFeedback(
        message_id=uuid.UUID(body.message_id),
        session_id=body.session_id,
        tenant_id=uuid.UUID(tenant_id),
        agent_id=uuid.UUID(body.agent_id),
        rating=body.rating,
        labels=body.labels or [],
        comment=pii_service.redact(body.comment) if body.comment else None,
        ideal_response=ideal_response_redacted,
        correction_reason=pii_service.redact(body.correction_reason) if body.correction_reason else None,
        playbook_correction=body.playbook_correction,
        tool_corrections=tool_corrections_raw or None,
        feedback_source=body.feedback_source or "user",
    )
    db.add(fb)
    await db.commit()
    await db.refresh(fb)

    has_correction = bool(body.ideal_response or body.playbook_correction or tool_corrections_raw)
    logger.info("feedback_submitted", tenant_id=tenant_id, rating=body.rating,
                has_correction=has_correction,
                tool_corrections=len(tool_corrections_raw),
                has_playbook_correction=bool(body.playbook_correction))

    # Push correction into Redis whenever any corrective signal is present
    # so the orchestrator injects it as a few-shot example on future turns.
    if has_correction and msg:
        await _store_correction_in_redis(
            request=request,
            agent_id=body.agent_id,
            user_message_content=pii_service.redact(msg.content),
            ideal_response=ideal_response_redacted,
            playbook_correction=body.playbook_correction,
            tool_corrections=tool_corrections_raw,
        )

    return _fb_to_response(fb)


@router.get("", response_model=list[FeedbackResponse])
async def list_feedback(
    request: Request,
    agent_id: Optional[str] = Query(None),
    rating: Optional[str] = Query(None, description="positive or negative"),
    session_id: Optional[str] = Query(None),
    has_correction: Optional[bool] = Query(None, description="Filter to only feedback with ideal_response"),
    include_messages: bool = Query(False, description="Include original user/assistant message content"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_tenant_db),
):
    """List feedback submissions for the tenant with optional filters."""
    tenant_id = _tenant_id(request)

    query = (
        select(MessageFeedback)
        .where(MessageFeedback.tenant_id == uuid.UUID(tenant_id))
        .order_by(MessageFeedback.created_at.desc(), MessageFeedback.id.desc())
        .offset(offset)
        .limit(limit)
    )
    if agent_id:
        query = query.where(MessageFeedback.agent_id == uuid.UUID(agent_id))
    
    # Apply deep isolation restriction if present (CRIT-005)
    raid = _restricted_agent_id(request)
    if raid:
        query = query.where(MessageFeedback.agent_id == raid)

    if rating:
        query = query.where(MessageFeedback.rating == rating)
    if session_id:
        query = query.where(MessageFeedback.session_id == session_id)
    if has_correction:
        query = query.where(MessageFeedback.ideal_response.is_not(None))

    result = await db.execute(query)
    feedback_items = result.scalars().all()

    # Optionally fetch message content for each feedback entry
    message_contents: dict[str, dict] = {}
    if include_messages and feedback_items:
        msg_ids = [fb.message_id for fb in feedback_items]
        msg_result = await db.execute(
            select(Message).where(Message.id.in_(msg_ids))
        )
        msgs_by_id = {str(m.id): m for m in msg_result.scalars().all()}

        # For each feedback, get the assistant message and preceding user message
        session_ids = list({fb.session_id for fb in feedback_items})
        for sess_id in session_ids:
            sess_msgs_result = await db.execute(
                select(Message)
                .where(Message.session_id == sess_id, Message.tenant_id == uuid.UUID(tenant_id))
                .order_by(Message.created_at.asc())
            )
            sess_msgs = list(sess_msgs_result.scalars().all())
            for i, msg in enumerate(sess_msgs):
                if str(msg.id) in msgs_by_id and msg.role == "assistant":
                    user_msg = sess_msgs[i - 1] if i > 0 and sess_msgs[i - 1].role == "user" else None
                    message_contents[str(msg.id)] = {
                        "agent_response": msg.content,
                        "user_message": user_msg.content if user_msg else None,
                    }

    return [_fb_to_response(fb, message_contents.get(str(fb.message_id))) for fb in feedback_items]


@router.get("/summary", response_model=FeedbackSummary)
async def feedback_summary(
    request: Request,
    agent_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_tenant_db),
):
    """Aggregate feedback stats: positive %, top labels, per-agent breakdown."""
    tenant_id = _tenant_id(request)

    # 1. Basic counts
    count_query = select(
        func.count(MessageFeedback.id),
        func.count(MessageFeedback.id).filter(MessageFeedback.rating == "positive")
    ).where(MessageFeedback.tenant_id == uuid.UUID(tenant_id))
    
    if agent_id:
        count_query = count_query.where(MessageFeedback.agent_id == uuid.UUID(agent_id))
    
    # Apply isolation (CRIT-005)
    raid = _restricted_agent_id(request)
    if raid:
        count_query = count_query.where(MessageFeedback.agent_id == raid)
        
    res = await db.execute(count_query)
    total, positive = res.one()
    negative = total - positive
    positive_pct = round(positive / total * 100, 1) if total else 0.0

    # 2. Top labels (expensive if we do it in Python on full dataset)
    # We'll stick to a simple query for labels if possible, but JSONB arrays make this tricky in SQL.
    # For now, we fetch the most recent 1000 items to guestimate labels if the dataset is huge,
    # or just use unnest in PG if we want perfect accuracy.
    
    # Accurate PG-specific label aggregation:
    label_query = select(
        func.jsonb_array_elements_text(MessageFeedback.labels).label("lbl"),
        MessageFeedback.rating,
        func.count()
    ).where(MessageFeedback.tenant_id == uuid.UUID(tenant_id))
    
    if agent_id:
        label_query = label_query.where(MessageFeedback.agent_id == uuid.UUID(agent_id))
    
    # Apply isolation (CRIT-005)
    raid = _restricted_agent_id(request)
    if raid:
        label_query = label_query.where(MessageFeedback.agent_id == raid)
        
    label_query = label_query.group_by("lbl", MessageFeedback.rating)
    label_res = await db.execute(label_query)
    
    pos_labels = []
    neg_labels = []
    for lbl, rating, count in label_res.all():
        if rating == "positive":
            pos_labels.append({"label": lbl, "count": count})
        else:
            neg_labels.append({"label": lbl, "count": count})
            
    pos_labels = sorted(pos_labels, key=lambda x: x["count"], reverse=True)[:10]
    neg_labels = sorted(neg_labels, key=lambda x: x["count"], reverse=True)[:10]

    # 3. Per-agent breakdown
    agent_query = select(
        MessageFeedback.agent_id,
        Agent.name,
        func.count(MessageFeedback.id).label("total"),
        func.count(MessageFeedback.id).filter(MessageFeedback.rating == "positive").label("positive")
    ).join(Agent, Agent.id == MessageFeedback.agent_id) \
     .where(MessageFeedback.tenant_id == uuid.UUID(tenant_id))

    # Apply isolation (CRIT-005)
    raid = _restricted_agent_id(request)
    if raid:
        agent_query = agent_query.where(MessageFeedback.agent_id == raid)

    agent_query = agent_query.group_by(MessageFeedback.agent_id, Agent.name)
     
    agent_res = await db.execute(agent_query)
    by_agent = []
    for aid, name, t, p in agent_res.all():
        by_agent.append({
            "agent_id": str(aid),
            "agent_name": name,
            "total": t,
            "positive": p,
            "negative": t - p,
            "positive_pct": round(p / t * 100, 1) if t else 0.0
        })

    return FeedbackSummary(
        total=total,
        positive=positive,
        negative=negative,
        positive_pct=positive_pct,
        top_positive_labels=pos_labels,
        top_negative_labels=neg_labels,
        by_agent=by_agent,
    )


@router.delete("/{feedback_id}", status_code=204)
async def delete_feedback(
    feedback_id: str,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
):
    """Delete a feedback entry by ID."""
    tenant_id = _tenant_id(request)
    query = select(MessageFeedback).where(
        MessageFeedback.id == uuid.UUID(feedback_id),
        MessageFeedback.tenant_id == uuid.UUID(tenant_id),
    )
    
    # Apply isolation (CRIT-005)
    raid = _restricted_agent_id(request)
    if raid:
        query = query.where(MessageFeedback.agent_id == raid)

    result = await db.execute(query)
    fb = result.scalar_one_or_none()
    if not fb:
        raise HTTPException(status_code=404, detail="Feedback not found.")

    # Also clean up from Redis corrections cache
    redis = getattr(request.app.state, "redis", None)
    if redis:
        key = CORRECTIONS_KEY.format(agent_id=str(fb.agent_id))
        try:
            # We match on the user message if available as it's the most stable key
            msg_result = await db.execute(select(Message).where(Message.id == fb.message_id))
            msg = msg_result.scalar_one_or_none()
            user_msg_content = None
            if msg:
                # Find the user message preceding this assistant message
                prev_msg_res = await db.execute(
                    select(Message).where(Message.session_id == fb.session_id, Message.created_at < msg.created_at)
                    .order_by(Message.created_at.desc()).limit(1)
                )
                prev = prev_msg_res.scalar_one_or_none()
                if prev and prev.role == "user":
                    user_msg_content = prev.content[:300]

            entries = await redis.lrange(key, 0, -1)
            for entry in entries:
                import json as _json
                parsed = _json.loads(entry)
                # Match by ideal response or user message prefix
                if (fb.ideal_response and parsed.get("ideal_response") == fb.ideal_response) or \
                   (user_msg_content and parsed.get("user_message") == user_msg_content):
                    await redis.lrem(key, 1, entry)
                    logger.info("feedback_redis_cleanup_success", agent_id=fb.agent_id)
                    break
        except Exception as e:
            logger.warning("feedback_redis_cleanup_failed", error=str(e))

    await db.delete(fb)
    await db.commit()


@router.get("/export")
async def export_feedback(
    request: Request,
    format: str = Query("jsonl", description="jsonl or csv"),
    agent_id: Optional[str] = Query(None),
    rating: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_tenant_db),
):
    """
    Export labelled feedback as JSONL or CSV with PII redaction and streaming.
    """
    tenant_id = _tenant_id(request)
    actor_id = getattr(request.state, "user_id", "unknown")
    
    # Zenith Pillar 4: Rate Throttling for high-resource exports
    redis = getattr(request.app.state, "redis", None)
    if redis:
        throttle_key = f"export_throttle:{tenant_id}:feedback"
        if await redis.get(throttle_key):
             raise HTTPException(status_code=429, detail="Export in progress or rate-limited. Please wait 1 minute.")
        await redis.setex(throttle_key, 60, "1")

    logger.info("feedback_export_requested", tenant_id=tenant_id, actor_id=actor_id, format=format)

    query = (
        select(MessageFeedback, Message)
        .join(Message, Message.id == MessageFeedback.message_id)
        .where(MessageFeedback.tenant_id == uuid.UUID(tenant_id))
        .order_by(MessageFeedback.created_at.desc())
    )
    if agent_id:
        query = query.where(MessageFeedback.agent_id == uuid.UUID(agent_id))
    
    # Apply isolation (CRIT-005)
    raid = _restricted_agent_id(request)
    if raid:
        query = query.where(MessageFeedback.agent_id == raid)

    if rating:
        query = query.where(MessageFeedback.rating == rating)

    result = await db.stream(query)

    async def generate():
        if format == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            yield "feedback_id,message_id,session_id,agent_id,rating,labels,comment,message_content,created_at\n"
            async for fb, msg in result:
                # Reuse the string IO buffer to avoid too many allocations
                output.seek(0)
                output.truncate(0)
                # Zenith Pillar 2: CSV Sanitization and PII Redaction
                clean_comment = pii_service.redact_for_display(fb.comment, None) or ""
                clean_msg = pii_service.redact_for_display(msg.content, None)[:1000]
                
                # Strip leading characters that could trigger formula injection
                if clean_comment and clean_comment[0] in ("=", "+", "-", "@"): clean_comment = "'" + clean_comment
                if clean_msg and clean_msg[0] in ("=", "+", "-", "@"): clean_msg = "'" + clean_msg

                writer.writerow([
                    str(fb.id), str(fb.message_id), fb.session_id, str(fb.agent_id),
                    fb.rating, "|".join(fb.labels or []), clean_comment,
                    clean_msg,
                    fb.created_at.isoformat() if fb.created_at else "",
                ])
                yield output.getvalue()
        else:
            async for fb, msg in result:
                yield json.dumps({
                    "feedback_id": str(fb.id),
                    "message_id": str(fb.message_id),
                    "session_id": fb.session_id,
                    "agent_id": str(fb.agent_id),
                    "rating": fb.rating,
                    "labels": fb.labels or [],
                    "comment": pii_service.redact_for_display(fb.comment, None),
                    "ideal_response": pii_service.redact_for_display(fb.ideal_response, None),
                    "message_content": pii_service.redact_for_display(msg.content, None),
                    "message_role": msg.role,
                    "created_at": fb.created_at.isoformat() if fb.created_at else "",
                }, ensure_ascii=False) + "\n"
            
            # Zenith Pillar 2: Terminal Forensic Marker
            yield f"\n# END OF AUDIT EXPORT # (Actor: {actor_id}, TS: {datetime.now(timezone.utc).isoformat()})\n"

    media_type = "text/csv" if format == "csv" else "application/x-ndjson"
    filename = f"feedback_export.{format}"
    
    return StreamingResponse(
        generate(),
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
