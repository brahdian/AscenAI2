from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.agent import Agent, AgentAnalytics, MessageFeedback
from app.schemas.chat import AgentAnalyticsSummary, AnalyticsOverview, DailyAnalytics

logger = structlog.get_logger(__name__)
router = APIRouter()


def _tenant_id(request: Request) -> str:
    tid = request.headers.get("X-Tenant-ID") or getattr(request.state, "tenant_id", None)
    if not tid:
        raise HTTPException(status_code=401, detail="Tenant ID required.")
    return tid


@router.get("/overview", response_model=AnalyticsOverview)
async def analytics_overview(
    request: Request,
    days: int = Query(30, ge=1, le=365, description="Number of days to look back"),
    agent_id: Optional[str] = Query(None, description="Filter to a single agent"),
    db: AsyncSession = Depends(get_db),
):
    """
    Return aggregated analytics for the given period.
    Includes daily time series and per-agent breakdown.
    """
    tenant_id = _tenant_id(request)
    since = date.today() - timedelta(days=days)

    # Build base query for AgentAnalytics rows
    query = select(AgentAnalytics).where(
        AgentAnalytics.tenant_id == uuid.UUID(tenant_id),
        AgentAnalytics.date >= since,
    )
    if agent_id:
        query = query.where(AgentAnalytics.agent_id == uuid.UUID(agent_id))

    result = await db.execute(query)
    rows: list[AgentAnalytics] = list(result.scalars().all())

    # Aggregate totals
    total_sessions = sum(r.total_sessions for r in rows)
    total_messages = sum(r.total_messages for r in rows)
    total_tokens = sum(r.total_tokens_used for r in rows)
    total_cost = round(sum(r.estimated_cost_usd for r in rows), 6)
    total_tools = sum(r.tool_executions for r in rows)
    total_escalations = sum(r.escalations for r in rows)

    weighted_latency = sum(r.avg_response_latency_ms * r.total_messages for r in rows)
    avg_latency = round(weighted_latency / total_messages, 1) if total_messages else 0.0

    # Daily time series (sum across agents per day)
    daily_map: dict[str, dict] = {}
    for r in rows:
        d = r.date.isoformat()
        if d not in daily_map:
            daily_map[d] = {
                "date": d,
                "total_sessions": 0,
                "total_messages": 0,
                "total_tokens": 0,
                "estimated_cost_usd": 0.0,
                "weighted_latency": 0.0,
                "tool_executions": 0,
                "escalations": 0,
                "successful_completions": 0,
            }
        e = daily_map[d]
        e["total_sessions"] += r.total_sessions
        e["total_messages"] += r.total_messages
        e["total_tokens"] += r.total_tokens_used
        e["estimated_cost_usd"] += r.estimated_cost_usd
        e["weighted_latency"] += r.avg_response_latency_ms * r.total_messages
        e["tool_executions"] += r.tool_executions
        e["escalations"] += r.escalations
        e["successful_completions"] += r.successful_completions

    daily = sorted(
        [
            DailyAnalytics(
                date=v["date"],
                total_sessions=v["total_sessions"],
                total_messages=v["total_messages"],
                total_tokens=v["total_tokens"],
                estimated_cost_usd=round(v["estimated_cost_usd"], 6),
                avg_latency_ms=round(v["weighted_latency"] / v["total_messages"], 1)
                if v["total_messages"] else 0.0,
                tool_executions=v["tool_executions"],
                escalations=v["escalations"],
                successful_completions=v["successful_completions"],
            )
            for v in daily_map.values()
        ],
        key=lambda x: x.date,
    )

    # Per-agent breakdown
    agent_map: dict[str, dict] = {}
    for r in rows:
        aid = str(r.agent_id)
        if aid not in agent_map:
            agent_map[aid] = {
                "agent_id": aid,
                "total_sessions": 0,
                "total_messages": 0,
                "total_tokens": 0,
                "estimated_cost_usd": 0.0,
                "weighted_latency": 0.0,
            }
        a = agent_map[aid]
        a["total_sessions"] += r.total_sessions
        a["total_messages"] += r.total_messages
        a["total_tokens"] += r.total_tokens_used
        a["estimated_cost_usd"] += r.estimated_cost_usd
        a["weighted_latency"] += r.avg_response_latency_ms * r.total_messages

    # Fetch agent names
    agents_result = await db.execute(
        select(Agent).where(Agent.tenant_id == uuid.UUID(tenant_id))
    )
    agent_names = {str(a.id): a.name for a in agents_result.scalars().all()}

    # Fetch feedback positive % per agent
    fb_query = select(
        MessageFeedback.agent_id,
        MessageFeedback.rating,
        func.count(MessageFeedback.id).label("cnt"),
    ).where(
        MessageFeedback.tenant_id == uuid.UUID(tenant_id),
        MessageFeedback.created_at >= datetime.combine(since, datetime.min.time()).replace(tzinfo=timezone.utc),
    ).group_by(MessageFeedback.agent_id, MessageFeedback.rating)
    fb_result = await db.execute(fb_query)
    fb_by_agent: dict[str, dict] = {}
    for row in fb_result.all():
        aid = str(row.agent_id)
        if aid not in fb_by_agent:
            fb_by_agent[aid] = {"positive": 0, "negative": 0}
        fb_by_agent[aid][row.rating] += row.cnt

    total_fb_pos = sum(v["positive"] for v in fb_by_agent.values())
    total_fb = sum(v["positive"] + v["negative"] for v in fb_by_agent.values())
    overall_pos_pct = round(total_fb_pos / total_fb * 100, 1) if total_fb else None

    by_agent = []
    for aid, a in agent_map.items():
        fb = fb_by_agent.get(aid, {})
        fb_total = fb.get("positive", 0) + fb.get("negative", 0)
        pos_pct = round(fb.get("positive", 0) / fb_total * 100, 1) if fb_total else None
        by_agent.append(
            AgentAnalyticsSummary(
                agent_id=aid,
                agent_name=agent_names.get(aid, "Unknown"),
                total_sessions=a["total_sessions"],
                total_messages=a["total_messages"],
                total_tokens=a["total_tokens"],
                estimated_cost_usd=round(a["estimated_cost_usd"], 6),
                avg_latency_ms=round(a["weighted_latency"] / a["total_messages"], 1)
                if a["total_messages"] else 0.0,
                positive_feedback_pct=pos_pct,
            )
        )
    by_agent.sort(key=lambda x: x.total_messages, reverse=True)

    return AnalyticsOverview(
        period_days=days,
        total_sessions=total_sessions,
        total_messages=total_messages,
        total_tokens=total_tokens,
        total_cost_usd=total_cost,
        avg_latency_ms=avg_latency,
        total_tool_executions=total_tools,
        total_escalations=total_escalations,
        feedback_positive_pct=overall_pos_pct,
        daily=daily,
        by_agent=by_agent,
    )
