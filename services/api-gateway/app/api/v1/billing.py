from __future__ import annotations

import uuid
import calendar
from datetime import date

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/billing")

# ---------------------------------------------------------------------------
# Plan definitions — update here when pricing changes
# ---------------------------------------------------------------------------

PLANS: dict[str, dict] = {
    # Overage rates are set well above COGS:
    # Real COGS per message ~$0.000185 (Gemini 2.5 Flash Lite @$0.10/$0.40 per 1M tok)
    # Real COGS per voice minute ~$0.026 (STT $0.14 + LLM $0.057 + TTS $0.72 + Twilio $0.0085 per min)
    "starter": {
        "display_name": "Starter",
        "price_per_agent": 49.00,
        "chat_messages_included": 1_000,
        "voice_minutes_included": 60,
        "playbooks_per_agent": 2,
        "rag_documents": 10,
        "team_seats": 1,
        "overage_per_message": 0.020,
        "overage_per_voice_minute": 0.20,
        "voice_enabled": True,
    },
    "professional": {
        "display_name": "Professional",
        "price_per_agent": 99.00,
        "chat_messages_included": 5_000,
        "voice_minutes_included": 200,
        "playbooks_per_agent": 5,
        "rag_documents": 25,
        "team_seats": 3,
        "overage_per_message": 0.015,
        "overage_per_voice_minute": 0.15,
        "voice_enabled": True,
    },
    # "growth" kept as alias for "business" — older tenants may have this key
    "growth": {
        "display_name": "Growth",
        "price_per_agent": 149.00,
        "chat_messages_included": 10_000,
        "voice_minutes_included": 500,
        "playbooks_per_agent": None,
        "rag_documents": 100,
        "team_seats": 5,
        "overage_per_message": 0.013,
        "overage_per_voice_minute": 0.13,
        "voice_enabled": True,
    },
    "business": {
        "display_name": "Business",
        "price_per_agent": 299.00,
        "chat_messages_included": 25_000,
        "voice_minutes_included": 1_000,
        "playbooks_per_agent": None,   # unlimited
        "rag_documents": 200,
        "team_seats": 10,
        "overage_per_message": 0.012,
        "overage_per_voice_minute": 0.12,
        "voice_enabled": True,
    },
    "enterprise": {
        "display_name": "Enterprise",
        "price_per_agent": None,       # custom
        "chat_messages_included": None,
        "voice_minutes_included": None,
        "playbooks_per_agent": None,
        "rag_documents": None,
        "team_seats": None,
        "overage_per_message": 0.00,
        "overage_per_voice_minute": 0.00,
        "voice_enabled": True,
    },
}

DEFAULT_PLAN = "starter"


def _get_plan(plan_key: str) -> dict:
    return PLANS.get(plan_key, PLANS[DEFAULT_PLAN])


def _require_tenant(request: Request) -> str:
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return tenant_id


def _billing_period() -> tuple[str, str]:
    today = date.today()
    start = date(today.year, today.month, 1)
    last_day = calendar.monthrange(today.year, today.month)[1]
    end = date(today.year, today.month, last_day)
    return start.isoformat(), end.isoformat()


def _calc_overage(plan: dict, messages: int, voice_minutes: float) -> float:
    """Calculate overage charges above plan limits."""
    included_msgs = plan["chat_messages_included"] or 0
    included_voice = plan["voice_minutes_included"] or 0

    msg_overage = max(0, messages - included_msgs)
    voice_overage = max(0.0, voice_minutes - included_voice)

    return round(
        msg_overage * plan["overage_per_message"]
        + voice_overage * plan["overage_per_voice_minute"],
        2,
    )


@router.get("/plans")
async def list_plans() -> dict:
    """Return all available plan definitions (used by the frontend pricing page)."""
    return {
        key: {k: v for k, v in plan.items()}
        for key, plan in PLANS.items()
    }


@router.get("/overview")
async def billing_overview(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant_id = _require_tenant(request)
    tenant_uuid = uuid.UUID(tenant_id)

    from app.models.tenant import Tenant, TenantUsage

    tenant_result = await db.execute(select(Tenant).where(Tenant.id == tenant_uuid))
    tenant = tenant_result.scalar_one_or_none()
    plan_key = (tenant.plan if tenant else DEFAULT_PLAN) or DEFAULT_PLAN
    plan = _get_plan(plan_key)

    usage_result = await db.execute(
        select(TenantUsage).where(TenantUsage.tenant_id == tenant_uuid)
    )
    usage_row = usage_result.scalar_one_or_none()

    if usage_row:
        sessions = usage_row.current_month_sessions or 0
        messages = usage_row.current_month_messages or 0
        tokens = usage_row.current_month_tokens or 0
        voice_minutes = float(usage_row.current_month_voice_minutes or 0)
        agent_count = usage_row.agent_count or 0
    else:
        sessions, messages, tokens, voice_minutes, agent_count = 0, 0, 0, 0.0, 0

    price_per_agent = plan["price_per_agent"] or 0
    base_cost = round(agent_count * price_per_agent, 2)
    overage = _calc_overage(plan, messages, voice_minutes)
    billing_start, billing_end = _billing_period()

    # Usage vs limits (None = unlimited)
    included_msgs = plan["chat_messages_included"]
    included_voice = plan["voice_minutes_included"]

    return {
        "plan": plan_key,
        "plan_display_name": plan["display_name"],
        "price_per_agent": price_per_agent,
        "agent_count": agent_count,
        "limits": {
            "chat_messages": included_msgs,
            "voice_minutes": included_voice,
            "team_seats": plan["team_seats"],
        },
        "usage": {
            "sessions": sessions,
            "messages": messages,
            "tokens": tokens,
            "voice_minutes": round(voice_minutes, 2),
            "messages_pct": round(messages / included_msgs * 100, 1) if included_msgs else None,
            "voice_pct": round(voice_minutes / included_voice * 100, 1) if included_voice else None,
        },
        "estimated_bill": {
            "base": base_cost,
            "overage": overage,
            "total": round(base_cost + overage, 2),
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
    tenant_id = _require_tenant(request)
    tenant_uuid = uuid.UUID(tenant_id)

    from app.models.tenant import Tenant, TenantUsage

    tenant_result = await db.execute(select(Tenant).where(Tenant.id == tenant_uuid))
    tenant = tenant_result.scalar_one_or_none()
    plan_key = (tenant.plan if tenant else DEFAULT_PLAN) or DEFAULT_PLAN
    plan = _get_plan(plan_key)
    price_per_agent = plan["price_per_agent"] or 0

    try:
        usage_result = await db.execute(
            select(TenantUsage).where(TenantUsage.tenant_id == tenant_uuid)
        )
        usage_row = usage_result.scalar_one_or_none()

        if not usage_row or not (usage_row.agent_count or 0):
            return []

        agent_count = usage_row.agent_count or 0
        total_sessions = (usage_row.current_month_sessions or 0)
        total_messages = (usage_row.current_month_messages or 0)
        total_tokens = (usage_row.current_month_tokens or 0)
        total_voice = float(usage_row.current_month_voice_minutes or 0)

        avg_sessions = total_sessions // agent_count if agent_count else 0
        avg_messages = total_messages // agent_count if agent_count else 0
        avg_tokens = total_tokens // agent_count if agent_count else 0
        avg_voice = round(total_voice / agent_count, 1) if agent_count else 0.0

        return [
            {
                "agent_id": None,
                "agent_name": f"Agent {i + 1}",
                "sessions": avg_sessions,
                "messages": avg_messages,
                "tokens": avg_tokens,
                "voice_minutes": avg_voice,
                "base_cost": price_per_agent,
                "overage": _calc_overage(plan, avg_messages, avg_voice),
                "total_cost": round(
                    price_per_agent + _calc_overage(plan, avg_messages, avg_voice), 2
                ),
            }
            for i in range(agent_count)
        ]
    except Exception as exc:
        logger.warning("billing_agents_error", error=str(exc))
        return []
