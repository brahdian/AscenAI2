from __future__ import annotations

import uuid
import calendar
import math
import httpx
from datetime import date

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/billing")


class CheckoutSessionRequest(BaseModel):
    plan: str = Field(..., description="Plan: text_growth, voice_growth, voice_business")

# ---------------------------------------------------------------------------
# Plan definitions — update here when pricing changes
# ---------------------------------------------------------------------------

PLANS: dict[str, dict] = {
    "starter": {
        "display_name": "Starter",
        "price_per_agent": 49.00,
        "chat_equivalents_included": 20_000,
        "base_chat_equivalents": 20_000,
        "voice_minutes_included": 0,
        "playbooks_per_agent": 5,
        "rag_documents": 50,
        "team_seats": 5,
        "overage_per_chat_equivalent": 0.002,
        "overage_per_voice_minute": 0.10,
        "voice_enabled": False,
        "model": "chat_equivalent",
    },
    "growth": {
        "display_name": "Growth",
        "price_per_agent": 99.00,
        "chat_equivalents_included": 80_000,
        "base_chat_equivalents": 20_000,
        "voice_minutes_included": 1500,
        "playbooks_per_agent": 5,
        "rag_documents": 50,
        "team_seats": 5,
        "overage_per_chat_equivalent": 0.002,
        "overage_per_voice_minute": 0.10,
        "voice_enabled": True,
        "model": "chat_equivalent",
    },
    "business": {
        "display_name": "Business",
        "price_per_agent": 199.00,
        "chat_equivalents_included": 170_000,
        "base_chat_equivalents": 20_000,
        "voice_minutes_included": 3500,
        "playbooks_per_agent": None,
        "rag_documents": 200,
        "team_seats": 10,
        "overage_per_chat_equivalent": 0.002,
        "overage_per_voice_minute": 0.10,
        "voice_enabled": True,
        "model": "chat_equivalent",
    },
    "enterprise": {
        "display_name": "Enterprise",
        "price_per_agent": None,
        "chat_equivalents_included": None,
        "base_chat_equivalents": None,
        "voice_minutes_included": None,
        "playbooks_per_agent": None,
        "rag_documents": None,
        "team_seats": None,
        "overage_per_chat_equivalent": 0.00,
        "overage_per_voice_minute": 0.00,
        "voice_enabled": True,
        "model": "chat_equivalent",
    },
}

DEFAULT_PLAN = "growth"


def _get_plan(plan_key: str) -> dict:
    # Handle DB keys like "voice_growth" by stripping prefix
    clean_key = plan_key.split("_")[-1] if "_" in plan_key else plan_key
    return PLANS.get(clean_key, PLANS.get(plan_key, PLANS[DEFAULT_PLAN]))


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


def _calc_overage(plan: dict, chats: int, voice_minutes: float) -> float:
    """Calculate overage charges using the chat equivalent model.
    
    Under the chat equivalent model, 1 voice minute = 100 chat equivalents.
    Users get a pool of "chat equivalents" they can use any way they want.
    Overage is charged for any chat equivalents used beyond the plan limit.
    """
    chat_equivalents = chats + int(voice_minutes * 100)
    included_chat_equivalents = plan["chat_equivalents_included"] or 0
    
    if chat_equivalents <= included_chat_equivalents:
        return 0.0
    
    overage_equivalents = chat_equivalents - included_chat_equivalents
    
    return round(
        overage_equivalents * plan["overage_per_chat_equivalent"],
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
    
    # Use tenant.plan or fallback to growth
    plan_key = (tenant.plan if tenant else DEFAULT_PLAN) or DEFAULT_PLAN
    plan = _get_plan(plan_key)

    usage_result = await db.execute(
        select(TenantUsage).where(TenantUsage.tenant_id == tenant_uuid)
    )
    usage_row = usage_result.scalar_one_or_none()

    if usage_row:
        sessions = usage_row.current_month_sessions or 0
        messages = usage_row.current_month_messages or 0
        chats = usage_row.current_month_chat_units or 0
        tokens = usage_row.current_month_tokens or 0
        voice_minutes = float(usage_row.current_month_voice_minutes or 0)
        agent_count = usage_row.agent_count or 0
    else:
        sessions, messages, chats, tokens, voice_minutes, agent_count = 0, 0, 0, 0, 0.0, 0

    # Ensure agent_count is at least 1 for active subscribers
    sub_status = getattr(tenant, "subscription_status", "inactive")
    if agent_count == 0 and tenant and sub_status == "active":
        agent_count = 1

    price_per_agent = plan["price_per_agent"] or 0
    base_cost = round(agent_count * price_per_agent, 2)
    overage = _calc_overage(plan, chats, voice_minutes)
    
    # Fetch period from Stripe if available, else month-end
    billing_start, billing_end = _billing_period()
    
    # Generate portal URL if tenant has Stripe customer ID
    portal_url = None
    if tenant and tenant.stripe_customer_id:
        try:
            import stripe
            stripe.api_key = settings.STRIPE_SECRET_KEY
            
            # If we have a subscription ID, we can get more accurate billing dates
            sub_id = getattr(tenant, "subscription_id", None)
            if sub_id:
                try:
                    subscription = stripe.Subscription.retrieve(sub_id)
                    billing_end = date.fromtimestamp(subscription.current_period_end).isoformat()
                    billing_start = date.fromtimestamp(subscription.current_period_start).isoformat()
                except Exception as sub_err:
                    logger.warning("stripe_sub_retrieve_error", error=str(sub_err))

            portal_session = stripe.billing_portal.Session.create(
                customer=tenant.stripe_customer_id,
                return_url=settings.FRONTEND_URL + "/dashboard/billing", # Corrected return URL
            )
            portal_url = portal_session.url
        except Exception as e:
            logger.warning("portal_session_error", error=str(e))

    return {
        "plan": plan_key,
        "plan_display_name": tenant.plan_display_name if tenant else plan["display_name"],
        "subscription_status": sub_status,
        "price_per_agent": price_per_agent,
        "agent_count": agent_count,
        "limits": {
            "chat_messages": plan["chat_equivalents_included"],
            "voice_minutes": plan["voice_minutes_included"],
            "team_seats": plan["team_seats"],
        },
        "usage": {
            "sessions": sessions,
            "messages": messages,
            "chats": chats,
            "tokens": tokens,
            "voice_minutes": round(voice_minutes, 2),
            "messages_pct": round(chats / (plan["chat_equivalents_included"] or 1) * 100, 1) if plan["chat_equivalents_included"] else 0.0,
            "voice_pct": round(voice_minutes / (plan["voice_minutes_included"] or 1) * 100, 1) if plan["voice_minutes_included"] else 0.0,
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
        "portal_url": portal_url,
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
        purchased_slots = usage_row.agent_count if usage_row else 0

        # Fetch actual agents from orchestrator
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{settings.AI_ORCHESTRATOR_URL}/api/v1/agents",
                headers={"X-Tenant-ID": tenant_id}
            )
            resp.raise_for_status()
            actual_agents = resp.json()

        # If tenant has an active subscription but no usage recorded yet, default slots to 1 for display
        sub_status = getattr(tenant, "subscription_status", "inactive")
        if purchased_slots == 0 and tenant and sub_status == "active":
            purchased_slots = 1

        total_sessions = (usage_row.current_month_sessions or 0) if usage_row else 0
        total_chats = (usage_row.current_month_chat_units or 0) if usage_row else 0
        total_voice = float(usage_row.current_month_voice_minutes or 0) if usage_row else 0.0

        # We display the actual agents first, then empty slots
        results = []
        for agent in actual_agents:
            # We don't have per-agent usage in the aggregate usage_row,
            # so we'll show 0 or N/A for now, or just focus on the name accuracy.
            # In a real system, we'd query per-agent analytics.
            results.append({
                "agent_id": agent["id"],
                "agent_name": agent["name"],
                "sessions": 0, # Placeholder until per-agent analytics are added
                "messages": 0,
                "voice_minutes": 0.0,
                "base_cost": price_per_agent,
                "status": "active" if agent.get("is_active") else "inactive",
                "total_cost": price_per_agent,
            })

        # Fill in remainining slots
        while len(results) < purchased_slots:
            results.append({
                "agent_id": None,
                "agent_name": "Available Slot",
                "sessions": 0,
                "messages": 0,
                "voice_minutes": 0.0,
                "base_cost": price_per_agent,
                "status": "available",
                "total_cost": price_per_agent,
            })

        return results
    except Exception as exc:
        logger.warning("billing_agents_error", error=str(exc))
        # Fallback to basic purchased slots if orchestrator is down
        return [
            {"agent_id": None, "agent_name": f"Agent Slot {i+1}", "base_cost": price_per_agent}
            for i in range(usage_row.agent_count if usage_row else 1)
        ]
    except Exception as exc:
        logger.warning("billing_agents_error", error=str(exc))
        return []


@router.post("/create-checkout-session")
async def create_checkout_session(
    body: CheckoutSessionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Create Stripe checkout session for subscription."""
    plan = body.plan
    tenant_id = _require_tenant(request)
    tenant_uuid = uuid.UUID(tenant_id)

    from app.models.tenant import Tenant

    tenant_result = await db.execute(select(Tenant).where(Tenant.id == tenant_uuid))
    tenant = tenant_result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    plan_data = _get_plan(plan)
    price = plan_data.get("price_per_agent")
    if not price:
        raise HTTPException(status_code=400, detail="Invalid plan or price not available")

    import stripe
    stripe.api_key = settings.STRIPE_SECRET_KEY

    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[
                {
                    "price_data": {
                        "currency": "usd",
                        "unit_amount": int(price * 100),
                        "recurring": {"interval": "month"},
                        "product_data": {
                            "name": f"AscenAI {plan_data['display_name']} Plan",
                        },
                    },
                    "quantity": 1,
                }
            ],
            mode="subscription",
            success_url=f"{settings.FRONTEND_URL}/billing?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{settings.FRONTEND_URL}/billing?cancelled=true",
            customer=tenant.stripe_customer_id,
            metadata={
                "tenant_id": str(tenant.id),
                "plan": plan,
            },
        )
        return {"checkout_url": checkout_session.url, "session_id": checkout_session.id}
    except stripe.error.StripeError as e:
        logger.warning("stripe_checkout_error", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to create checkout session")


@router.post("/create-agent-slot-session")
async def create_agent_slot_session(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Create Stripe checkout session for a single new agent slot."""
    tenant_id = _require_tenant(request)
    tenant_uuid = uuid.UUID(tenant_id)

    from app.models.tenant import Tenant
    tenant_result = await db.execute(select(Tenant).where(Tenant.id == tenant_uuid))
    tenant = tenant_result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    plan_data = _get_plan(tenant.plan or DEFAULT_PLAN)
    price = plan_data.get("price_per_agent") or 99.00

    import stripe
    stripe.api_key = settings.STRIPE_SECRET_KEY

    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[
                {
                    "price_data": {
                        "currency": "usd",
                        "unit_amount": int(price * 100),
                        "recurring": {"interval": "month"},
                        "product_data": {
                            "name": "Additional AI Agent Slot",
                            "description": f"Standard {plan_data['display_name']} agent slot",
                        },
                    },
                    "quantity": 1,
                }
            ],
            mode="subscription",
            success_url=f"{settings.FRONTEND_URL}/dashboard/billing?success=true",
            cancel_url=f"{settings.FRONTEND_URL}/dashboard/billing?cancelled=true",
            customer=tenant.stripe_customer_id,
            metadata={
                "tenant_id": str(tenant.id),
                "action": "add_agent_slot",
            },
        )
        return {"checkout_url": checkout_session.url}
    except stripe.error.StripeError as e:
        logger.warning("stripe_slot_checkout_error", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to create checkout session")


@router.post("/portal-session")
async def create_portal_session(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Create a Stripe customer portal session for managing billing."""
    tenant_id = _require_tenant(request)
    tenant_uuid = uuid.UUID(tenant_id)
    
    from app.models.tenant import Tenant
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_uuid))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    
    if not tenant.stripe_customer_id:
        raise HTTPException(status_code=400, detail="No Stripe customer found")
    
    import stripe
    stripe.api_key = settings.STRIPE_SECRET_KEY
    
    session = stripe.billing_portal.Session.create(
        customer=tenant.stripe_customer_id,
        return_url=settings.FRONTEND_URL + "/dashboard/billing",
    )
    return {"portal_url": session.url}


@router.get("/invoices")
async def list_invoices(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """List recent invoices from Stripe."""
    tenant_id = _require_tenant(request)
    tenant_uuid = uuid.UUID(tenant_id)
    
    from app.models.tenant import Tenant
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_uuid))
    tenant = result.scalar_one_or_none()
    if not tenant or not tenant.stripe_customer_id:
        return {"invoices": []}
    
    import stripe
    stripe.api_key = settings.STRIPE_SECRET_KEY
    
    invoices = stripe.Invoice.list(
        customer=tenant.stripe_customer_id,
        limit=10,
    )
    return {
        "invoices": [
            {
                "id": inv.id,
                "amount_due": inv.amount_due,
                "amount_paid": inv.amount_paid,
                "status": inv.status,
                "created": inv.created,
                "invoice_pdf": inv.invoice_pdf,
                "hosted_invoice_url": inv.hosted_invoice_url,
            }
            for inv in invoices.data
        ]
    }
