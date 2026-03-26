from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/billing")

# Pricing: $100 per active agent per month
AGENT_MONTHLY_COST = 100.00


def _require_tenant(request: Request) -> str:
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return tenant_id


def _billing_period() -> tuple[str, str]:
    """Returns (start, end) ISO date strings for the current calendar month."""
    today = date.today()
    start = date(today.year, today.month, 1)
    # End of current month
    if today.month == 12:
        end = date(today.year + 1, 1, 1)
    else:
        end = date(today.year, today.month + 1, 1)
    # Last day of this month
    import calendar
    last_day = calendar.monthrange(today.year, today.month)[1]
    end = date(today.year, today.month, last_day)
    return start.isoformat(), end.isoformat()


@router.get("/overview")
async def billing_overview(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Returns billing overview for the current tenant.
    Pricing: $100/agent/month flat rate (counts active agents).
    """
    tenant_id = _require_tenant(request)
    tenant_uuid = uuid.UUID(tenant_id)

    # Import models here to avoid circular imports at module level
    from app.models.tenant import Tenant

    # Get tenant plan
    tenant_result = await db.execute(
        select(Tenant).where(Tenant.id == tenant_uuid)
    )
    tenant = tenant_result.scalar_one_or_none()
    plan = tenant.plan if tenant else "professional"

    # Count active agents via orchestrator DB or usage data
    # We query usage from TenantUsage or approximate via analytics
    # For billing, we need the agent count — proxy via analytics or a direct count
    # Since agents live in ai-orchestrator DB, we use TenantUsage.agents_count if available
    from app.models.tenant import TenantUsage
    usage_result = await db.execute(
        select(TenantUsage).where(TenantUsage.tenant_id == tenant_uuid)
    )
    usage_row = usage_result.scalar_one_or_none()

    # Pull usage figures from TenantUsage
    if usage_row:
        sessions = usage_row.sessions_this_month or 0
        messages = usage_row.messages_this_month or 0
        tokens = usage_row.tokens_this_month or 0
        voice_minutes = float(usage_row.voice_minutes_this_month or 0)
        agent_count = usage_row.agents_count or 0
    else:
        sessions, messages, tokens, voice_minutes, agent_count = 0, 0, 0, 0.0, 0

    monthly_agent_cost = round(agent_count * AGENT_MONTHLY_COST, 2)
    billing_start, billing_end = _billing_period()

    return {
        "plan": plan,
        "agent_count": agent_count,
        "monthly_agent_cost": monthly_agent_cost,
        "usage": {
            "sessions": sessions,
            "messages": messages,
            "tokens": tokens,
            "voice_minutes": round(voice_minutes, 2),
        },
        "estimated_bill": {
            "agents": monthly_agent_cost,
            "overage": 0.00,
            "total": monthly_agent_cost,
        },
        "billing_period": {
            "start": billing_start,
            "end": billing_end,
        },
    }


@router.get("/agents")
async def billing_agents(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """
    Per-agent cost breakdown.
    Returns agent name, sessions, tokens, and cost for the current billing period.
    """
    tenant_id = _require_tenant(request)
    tenant_uuid = uuid.UUID(tenant_id)

    today = date.today()
    period_start = date(today.year, today.month, 1)

    # Query analytics aggregated by agent for this month
    # AgentAnalytics lives in ai-orchestrator, but we proxy via the orchestrator URL
    # For now, return data from TenantUsage or empty if not available
    # A production implementation would query the orchestrator's analytics endpoint
    try:
        from app.models.tenant import TenantUsage
        usage_result = await db.execute(
            select(TenantUsage).where(TenantUsage.tenant_id == tenant_uuid)
        )
        usage_row = usage_result.scalar_one_or_none()

        if not usage_row or not (usage_row.agents_count or 0):
            return []

        # Return a summary-level breakdown (agent-level data requires orchestrator DB access)
        agent_count = usage_row.agents_count or 0
        total_sessions = (usage_row.sessions_this_month or 0)
        total_tokens = (usage_row.tokens_this_month or 0)

        avg_sessions = total_sessions // agent_count if agent_count else 0
        avg_tokens = total_tokens // agent_count if agent_count else 0

        return [
            {
                "agent_id": None,
                "agent_name": f"Agent {i + 1}",
                "sessions": avg_sessions,
                "tokens": avg_tokens,
                "cost": AGENT_MONTHLY_COST,
            }
            for i in range(agent_count)
        ]
    except Exception as exc:
        logger.warning("billing_agents_error", error=str(exc))
        return []
