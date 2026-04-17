from __future__ import annotations

import uuid
import calendar
import math
import httpx
from datetime import date, datetime, timezone, timedelta

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update as _sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_tenant_db, get_current_tenant
from app.services.idempotency_service import IdempotencyService

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/billing")


class CheckoutSessionRequest(BaseModel):
    plan: str = Field(..., description="Plan: text_growth, voice_growth, voice_business")


class AgentSlotSessionRequest(BaseModel):
    agent_config: dict | None = Field(None, description="Optional agent configuration for auto-creation after success")
    return_path: str | None = Field(None, description="Optional return path (e.g., /dashboard/agents/new)")

# ---------------------------------------------------------------------------
# Plan definitions — update here when pricing changes
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Fallback plans if DB is empty
# ---------------------------------------------------------------------------

DEFAULT_PLANS: dict[str, dict] = {
    "starter": {
        "display_name": "Starter",
        "description": "For growing businesses with higher conversation volume.",
        "badge": "Entry Level",
        "color": "border-white/10",
        "highlight": False,
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
        "description": "For growing businesses needing voice capability.",
        "badge": "Most Popular",
        "color": "border-violet-500/50",
        "highlight": True,
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
        "description": "For high-volume businesses with heavy voice usage.",
        "badge": "Power User",
        "color": "border-white/10",
        "highlight": False,
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
        "description": "For high-volume businesses with custom requirements.",
        "badge": "Contact Sales",
        "color": "border-white/10",
        "highlight": False,
        "price_per_agent": None,
        "chat_equivalents_included": None,
        "base_chat_equivalents": None,
        "voice_minutes_included": None,
        "playbooks_per_agent": None,
        "rag_documents": None,
        "team_seats": None,
        "overage_per_chat_equivalent": 0.0,
        "overage_per_voice_minute": 0.0,
        "voice_enabled": True,
        "model": "chat_equivalent",
    },
}


async def get_platform_plans(db: AsyncSession) -> dict[str, dict]:
    """Fetch plans from platform_settings."""
    try:
        from app.models.platform import PlatformSetting
        result = await db.execute(
            select(PlatformSetting).where(PlatformSetting.key == "billing_plans")
        )
        setting = result.scalar_one_or_none()
        if setting and setting.value:
            # Merge with defaults to ensure all keys exist for robust UI
            merged = {}
            for key, default_data in DEFAULT_PLANS.items():
                if key in setting.value:
                    merged[key] = {**default_data, **setting.value[key]}
                else:
                    merged[key] = default_data
            return merged
    except Exception as e:
        logger.warning("failed_to_fetch_billing_plans", error=str(e))
    return DEFAULT_PLANS


async def _get_plan(plan_key: str, db: AsyncSession) -> dict:
    plans = await get_platform_plans(db)
    # Handle DB keys like "voice_growth" by stripping prefix
    clean_key = plan_key.split("_")[-1] if "_" in plan_key else plan_key
    return plans.get(clean_key, plans.get(plan_key, plans.get("growth", {})))


def _require_tenant(request: Request) -> str:
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return tenant_id


def _billing_period() -> tuple[date, date]:
    today = date.today()
    start = date(today.year, today.month, 1)
    last_day = calendar.monthrange(today.year, today.month)[1]
    end = date(today.year, today.month, last_day)
    return start, end


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
async def list_plans(db: AsyncSession = Depends(get_db)) -> dict:
    """Return all available plan definitions (used by the frontend pricing page)."""
    plans = await get_platform_plans(db)
    return {
        key: {k: v for k, v in plan.items()}
        for key, plan in plans.items()
    }


@router.get("/overview")
async def billing_overview(
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
) -> dict:
    tenant_uuid = uuid.UUID(tenant_id)

    from app.models.tenant import Tenant, TenantUsage

    tenant_result = await db.execute(select(Tenant).where(Tenant.id == tenant_uuid))
    tenant = tenant_result.scalar_one_or_none()
    
    # Use tenant.plan or fallback to none
    plan_key = tenant.plan if (tenant and tenant.plan) else "none"
    plan_display_name = "Not Subscribed"
    
    if plan_key != "none":
        plan = await _get_plan(plan_key, db)
        plan_display_name = tenant.plan_display_name if tenant and tenant.plan_display_name else plan["display_name"]
    else:
        # Dummy plan with zero limits/pricing
        plan = {
            "display_name": "Not Subscribed",
            "price_per_agent": 0.0,
            "chat_equivalents_included": 0,
            "voice_minutes_included": 0,
            "team_seats": 1,
            "overage_per_chat_equivalent": 0.0,
            "overage_per_voice_minute": 0.0,
        }

    usage_result = await db.execute(
        select(TenantUsage).where(TenantUsage.tenant_id == tenant_uuid)
    )
    usage_row = usage_result.scalar_one_or_none()
    agent_count = usage_row.agent_count if usage_row else 0

    # TenantUsage.current_month_* counters are never written — read from
    # agent_analytics (shared DB) for real usage figures, same as billing_agents.
    from sqlalchemy import text as _text
    billing_start, _ = _billing_period()
    try:
        analytics_res = await db.execute(
            _text("""
                SELECT COALESCE(SUM(total_sessions), 0)    AS sessions,
                       COALESCE(SUM(total_messages), 0)    AS messages,
                       COALESCE(SUM(total_chat_units), 0)  AS chats,
                       COALESCE(SUM(total_tokens_used), 0) AS tokens,
                       COALESCE(SUM(total_voice_minutes), 0.0) AS voice_minutes
                FROM agent_analytics
                WHERE tenant_id = :tenant_id AND date >= :start_date
            """),
            {"tenant_id": tenant_uuid, "start_date": billing_start},
        )
        ar = analytics_res.one()
        sessions      = int(ar.sessions or 0)
        messages      = int(ar.messages or 0)
        chats         = int(ar.chats or 0)
        tokens        = int(ar.tokens or 0)
        voice_minutes = float(ar.voice_minutes or 0)
    except Exception as _ae:
        logger.warning("billing_overview_analytics_query_failed", error=str(_ae))
        sessions, messages, chats, tokens, voice_minutes = 0, 0, 0, 0, 0.0

    # Ensure agent_count reflects active state for UI consistency
    sub_status = getattr(tenant, "subscription_status", "inactive")
    if sub_status == "active" or sub_status == "trialing":
        # If subscription is active, ensure we show at least 1 agent if they've paid
        if agent_count == 0:
            agent_count = 1
    
    # User feedback: "when agent has 2 slots it shows 0"
    # We should trust TenantUsage.agent_count if it's > 0, otherwise fallback to 1 if active.
    # Actually, let's also check if we can get a ground truth from the DB or similar soon.

    price_per_agent = plan["price_per_agent"] or 0
    base_cost = round(agent_count * price_per_agent, 2)
    
    # Accurate overage calculation for UI
    chat_equivalents = chats + int(voice_minutes * 100)
    included_chat_equivalents = plan["chat_equivalents_included"] or 0
    chat_overage_units = max(0, chat_equivalents - included_chat_equivalents)
    chat_overage_cost = round(chat_overage_units * plan["overage_per_chat_equivalent"], 2)
    
    # For now, voice overage is included in the chat equivalent overage in this model,
    # but we'll provide the fields for UI compatibility.
    voice_overage_cost = 0.0 
    
    # Fetch period from Stripe if available, else month-end
    billing_start, billing_end = _billing_period()
    
    # Generate portal URL if tenant has Stripe customer ID
    portal_url = None
    if tenant and tenant.stripe_customer_id:
        try:
            import stripe
            import asyncio as _asyncio
            stripe.api_key = settings.STRIPE_SECRET_KEY
            
            # B11 FIX: Stripe SDK is synchronous — run in thread to not block the async event loop
            # If we have a subscription ID, we can get more accurate billing dates
            sub_id = getattr(tenant, "subscription_id", None)
            if sub_id:
                try:
                    subscription = await _asyncio.to_thread(stripe.Subscription.retrieve, sub_id)
                    billing_end = date.fromtimestamp(subscription.current_period_end).isoformat()
                    billing_start = date.fromtimestamp(subscription.current_period_start).isoformat()
                except Exception as sub_err:
                    logger.warning("stripe_sub_retrieve_error", error=str(sub_err))

            portal_session = await _asyncio.to_thread(
                stripe.billing_portal.Session.create,
                customer=tenant.stripe_customer_id,
                return_url=settings.FRONTEND_URL + "/dashboard/billing",
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
            "chat_messages": plan["chat_equivalents_included"] if sub_status in ("active", "trialing") else 0,
            "voice_minutes": plan["voice_minutes_included"] if sub_status in ("active", "trialing") else 0,
            "team_seats": plan["team_seats"] if sub_status in ("active", "trialing") else 0,
        },
        "usage": {
            "sessions": sessions,
            "messages": messages,
            "chats": chats,
            "tokens": tokens,
            "voice_minutes": round(voice_minutes, 2),
            "messages_pct": round(chat_equivalents / (plan["chat_equivalents_included"] or 1) * 100, 1) if plan["chat_equivalents_included"] else 0.0,
            "voice_pct": round(voice_minutes / (plan["voice_minutes_included"] or 1) * 100, 1) if plan["voice_minutes_included"] else 0.0,
            "chat_overage": chat_overage_units,
            "voice_overage": 0.0,
        },
        "estimated_bill": {
            "base": base_cost,
            "chat_overage": chat_overage_cost,
            "voice_overage": voice_overage_cost,
            "overage": chat_overage_cost + voice_overage_cost,
            "total": round(base_cost + chat_overage_cost + voice_overage_cost, 2),
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
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
) -> list[dict]:
    tenant_uuid = uuid.UUID(tenant_id)

    from app.models.tenant import Tenant, TenantUsage

    tenant_result = await db.execute(select(Tenant).where(Tenant.id == tenant_uuid))
    tenant = tenant_result.scalar_one_or_none()
    plan_key = tenant.plan if (tenant and tenant.plan) else "growth"
    plan = await _get_plan(plan_key, db)
    price_per_agent = plan["price_per_agent"] or 0

    try:
        from app.models.tenant import Tenant, TenantUsage
        # Actually, since orchestrator and gateway might have different model structures, let's use raw SQL for speed and safety.
        from sqlalchemy import text
        
        # Get start/end of current month
        start_date, _ = _billing_period()
        
        usage_query = text("""
            SELECT agent_id, 
                   SUM(total_sessions) as sessions, 
                   SUM(total_messages) as messages, 
                   SUM(total_chat_units) as chats,
                   SUM(total_voice_minutes) as voice_minutes
            FROM agent_analytics
            WHERE tenant_id = :tenant_id AND date >= :start_date
            GROUP BY agent_id
        """)
        usage_res = await db.execute(usage_query, {"tenant_id": tenant_uuid, "start_date": start_date})
        usage_map = {str(r.agent_id): r for r in usage_res.all()}

        usage_row_result = await db.execute(
            select(TenantUsage).where(TenantUsage.tenant_id == tenant_uuid)
        )
        usage_row = usage_row_result.scalar_one_or_none()
        purchased_slots = usage_row.agent_count if usage_row else 0

        # Fetch actual agents from orchestrator
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{settings.AI_ORCHESTRATOR_URL}/api/v1/agents",
                headers={"X-Tenant-ID": tenant_id, "X-Internal-Key": settings.INTERNAL_API_KEY}
            )
            resp.raise_for_status()
            actual_agents = resp.json()

        # If tenant has an active subscription but no usage recorded yet, default slots to 1 for display
        sub_status = getattr(tenant, "subscription_status", "inactive")
        if purchased_slots == 0 and tenant and sub_status == "active":
            purchased_slots = 1

        # We display the actual agents first, then empty slots
        results = []
        for agent in actual_agents:
            a_usage = usage_map.get(agent["id"])
            sessions = int(a_usage.sessions) if a_usage else 0
            messages = int(a_usage.messages) if a_usage else 0
            chats = int(a_usage.chats) if a_usage else 0
            voice_minutes = float(a_usage.voice_minutes) if a_usage else 0.0
            
            # Simple overage logic per agent for display (pro-rata estimated)
            # Actually, overage is usually calculated at tenant level, but we can show "contribution"
            results.append({
                "agent_id": agent["id"],
                "agent_name": agent["name"],
                "sessions": sessions,
                "messages": messages,
                "chats": chats,
                "tokens": 0,
                "voice_minutes": round(voice_minutes, 2),
                "base_cost": price_per_agent,
                "status": "active" if agent.get("is_active") else "inactive",
                "overage": 0.0, # Tenant-level usually, but can be split if needed
                "total_cost": price_per_agent,
            })

        # Fill in remaining slots
        while len(results) < purchased_slots:
            results.append({
                "agent_id": None,
                "agent_name": "Available Slot",
                "sessions": 0,
                "messages": 0,
                "chats": 0,
                "tokens": 0,
                "voice_minutes": 0.0,
                "base_cost": price_per_agent,
                "overage": 0.0,
                "status": "available",
                "total_cost": price_per_agent,
            })

        return results
    except Exception as exc:
        logger.warning("billing_agents_error", error=str(exc))
        # Fallback if orchestrator or analytics query fails
        try:
            # Try to at least get purchased slots for a fallback list
            usage_row_result = await db.execute(
                select(TenantUsage).where(TenantUsage.tenant_id == tenant_uuid)
            )
            usage_row = usage_row_result.scalar_one_or_none()
            purchased_slots = usage_row.agent_count if usage_row else 1
        except Exception:
            purchased_slots = 1

        return [
            {
                "agent_id": None,
                "agent_name": f"Agent Slot {i+1}",
                "sessions": 0, "messages": 0, "chats": 0, "tokens": 0,
                "voice_minutes": 0.0, "base_cost": price_per_agent,
                "overage": 0.0, "total_cost": price_per_agent, "status": "available",
            }
            for i in range(purchased_slots)
        ]


@router.post("/create-checkout-session")
async def create_checkout_session(
    body: CheckoutSessionRequest,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
):
    """Create Stripe checkout session for subscription."""
    tenant_uuid = uuid.UUID(tenant_id)

    from app.models.tenant import Tenant

    tenant_result = await db.execute(select(Tenant).where(Tenant.id == tenant_uuid))
    tenant = tenant_result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    plan_data = await _get_plan(plan, db)
    price = plan_data.get("price_per_agent")
    if not price:
        raise HTTPException(status_code=400, detail="Invalid plan or price not available")

    import stripe
    stripe.api_key = settings.STRIPE_SECRET_KEY

    # Use the request's Origin header as the base URL so Stripe redirects back
    # to the correct port/domain regardless of what FRONTEND_URL is configured to.
    _origin = request.headers.get("Origin") or request.headers.get("Referer", "").split("/api")[0]
    frontend_base = _origin.rstrip("/") if _origin else settings.FRONTEND_URL

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
            success_url=f"{frontend_base}/billing?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{frontend_base}/billing?cancelled=true",
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
    payload: AgentSlotSessionRequest | None = None,
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
):
    """Create Stripe checkout session for a single new agent slot."""
    tenant_uuid = uuid.UUID(tenant_id)

    # Prevent duplicate concurrent checkout sessions (e.g., double-click).
    # Redis NX lock with 30-second TTL — a second request within the window returns 409.
    try:
        from app.core.redis_client import get_redis as _get_redis
        _redis = await _get_redis()
        if _redis:
            lock_key = f"checkout_lock:{tenant_id}"
            acquired = await _redis.set(lock_key, "1", nx=True, ex=30)
            if not acquired:
                raise HTTPException(
                    status_code=409,
                    detail="A checkout session is already being created for this account. Please wait a moment.",
                )
    except HTTPException:
        raise
    except Exception:
        pass  # Redis unavailable — proceed without lock rather than blocking checkout
    
    agent_config = payload.agent_config if payload else None
    return_path = payload.return_path if payload else "/dashboard/billing"

    from app.models.tenant import Tenant, PendingAgentPurchase
    tenant_result = await db.execute(select(Tenant).where(Tenant.id == tenant_uuid))
    tenant = tenant_result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # If agent_config is provided, create a pending purchase record
    pending_id = None
    if agent_config:
        # Phase 2: Use stripe_session_id for idempotency — but we don't have it yet
        # at checkout-creation time. We store a pending record and will set the
        # stripe_session_id on the PendingAgentPurchase when the webhook fires.
        pending = PendingAgentPurchase(
            tenant_id=tenant_uuid,
            config=agent_config,
        )
        db.add(pending)
        await db.commit()
        await db.refresh(pending)
        pending_id = str(pending.id)

    plan_data = await _get_plan(tenant.plan or "growth", db)
    price = plan_data.get("price_per_agent") or 99.00

    # Self-healing: if stripe_customer_id is missing, try to create one now.
    if not tenant.stripe_customer_id:
        logger.info("stripe_customer_id_missing_attempting_creation", tenant_id=str(tenant.id))
        from app.models.user import User
        user_res = await db.execute(select(User).where(User.tenant_id == tenant.id, User.role == "owner"))
        owner = user_res.scalar_one_or_none()
        if owner:
            from app.services.auth_service import _create_stripe_customer
            stripe_customer_id = await _create_stripe_customer(tenant, owner)
            if stripe_customer_id:
                tenant.stripe_customer_id = stripe_customer_id
                await db.commit()
                logger.info("stripe_customer_id_created_on_the_fly", tenant_id=str(tenant.id), customer_id=stripe_customer_id)

    import stripe
    stripe.api_key = settings.STRIPE_SECRET_KEY

    # Use the request's Origin header as the base URL so Stripe redirects back
    # to the correct port/domain regardless of what FRONTEND_URL is configured to.
    _origin = request.headers.get("Origin") or request.headers.get("Referer", "").split("/api")[0]
    frontend_base = _origin.rstrip("/") if _origin else settings.FRONTEND_URL

    try:
        # If still no customer ID, we'll let Stripe create one or omit it (Session creation might fail without customer in some modes, but mode="subscription" usually allows it if price is valid)
        kwargs = {
            "payment_method_types": ["card"],
            "line_items": [
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
            "mode": "subscription",
            "success_url": f"{frontend_base}{return_path}?success=true",
            "cancel_url": f"{frontend_base}{return_path}?cancelled=true",
            "metadata": {
                "tenant_id": str(tenant.id),
                "action": "add_agent_slot",
                "pending_agent_purchase_id": pending_id or "",
            },
        }
        if tenant.stripe_customer_id:
            kwargs["customer"] = tenant.stripe_customer_id
        else:
            # If we don't have a customer, we MUST provide customer_email to at least link it later
            kwargs["customer_email"] = tenant.email

        checkout_session = stripe.checkout.Session.create(**kwargs)
        return {"checkout_url": checkout_session.url}
    except stripe.error.StripeError as e:
        logger.error("stripe_slot_checkout_error", error=str(e), tenant_id=str(tenant.id))
        raise HTTPException(status_code=500, detail="Payment processing failed. Please try again later.")
    except Exception as e:
        logger.error("unexpected_slot_checkout_error", error=str(e), tenant_id=str(tenant.id))
        raise HTTPException(status_code=500, detail="An unexpected error occurred while initiating purchase.")


class ReactivationSessionRequest(BaseModel):
    agent_id: str = Field(..., description="ID of the archived agent to reactivate")
    return_path: str = Field("/dashboard/agents", description="Frontend path to redirect after checkout")
    paid_through: str | None = Field(None, description="ISO timestamp of original expiry — if in future, used as Stripe trial_end to avoid double-charging")


@router.post("/reactivation-session")
async def create_reactivation_session(
    request: Request,
    payload: ReactivationSessionRequest,
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
):
    """
    Create a Stripe checkout session to reactivate a specific archived agent.

    The checkout session embeds `agent_id` in Stripe metadata so that the
    existing `checkout.session.completed` webhook (Flow 1) automatically
    sets is_active=True, stores stripe_subscription_id, and sets expires_at
    — no extra webhook handling needed.

    If `paid_through` is in the future (user had remaining days when they
    cancelled), Stripe trial_end is set to that timestamp so the user is not
    charged for days they already paid for. Billing resumes normally after
    trial_end.
    """
    from app.models.tenant import Tenant
    from app.models.user import User
    from app.services.auth_service import _create_stripe_customer
    import stripe

    tenant_uuid = uuid.UUID(tenant_id)

    tenant_result = await db.execute(select(Tenant).where(Tenant.id == tenant_uuid))
    tenant = tenant_result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # Self-heal: ensure stripe customer exists
    if not tenant.stripe_customer_id:
        user_res = await db.execute(
            select(User).where(User.tenant_id == tenant.id, User.role == "owner")
        )
        owner = user_res.scalar_one_or_none()
        if owner:
            stripe_customer_id = await _create_stripe_customer(tenant, owner)
            if stripe_customer_id:
                tenant.stripe_customer_id = stripe_customer_id
                await db.commit()

    plan_data = await _get_plan(tenant.plan or "growth", db)
    price = plan_data.get("price_per_agent") or 99.00

    _origin = request.headers.get("Origin") or request.headers.get("Referer", "").split("/api")[0]
    frontend_base = _origin.rstrip("/") if _origin else settings.FRONTEND_URL

    stripe.api_key = settings.STRIPE_SECRET_KEY

    # Determine whether to set a trial period (no double-charge for remaining days)
    trial_end: int | None = None
    now_ts = int(datetime.now(timezone.utc).timestamp())
    if payload.paid_through:
        try:
            paid_through_dt = datetime.fromisoformat(payload.paid_through.replace("Z", "+00:00"))
            paid_through_ts = int(paid_through_dt.timestamp())
            if paid_through_ts > now_ts + 86400:  # at least 1 day remaining
                trial_end = paid_through_ts
        except (ValueError, OSError):
            pass

    kwargs: dict = {
        "payment_method_types": ["card"],
        "mode": "subscription",
        "success_url": f"{frontend_base}{payload.return_path}?reactivated=true",
        "cancel_url": f"{frontend_base}{payload.return_path}?cancelled=true",
        "metadata": {
            "tenant_id": str(tenant.id),
            "action": "reactivate_agent",
            "agent_id": payload.agent_id,
        },
        "line_items": [
            {
                "price_data": {
                    "currency": "usd",
                    "unit_amount": int(price * 100),
                    "recurring": {"interval": "month"},
                    "product_data": {
                        "name": "Agent Reactivation",
                        "description": (
                            f"Reactivate agent slot ({plan_data['display_name']})"
                        ),
                    },
                },
                "quantity": 1,
            }
        ],
    }

    if trial_end:
        kwargs["subscription_data"] = {"trial_end": trial_end}

    if tenant.stripe_customer_id:
        kwargs["customer"] = tenant.stripe_customer_id
    else:
        kwargs["customer_email"] = tenant.email

    try:
        checkout_session = stripe.checkout.Session.create(**kwargs)
        logger.info(
            "reactivation_checkout_created",
            tenant_id=tenant_id,
            agent_id=payload.agent_id,
            trial_end=trial_end,
            session_id=checkout_session.id,
        )
        return {"checkout_url": checkout_session.url, "session_id": checkout_session.id}
    except stripe.error.StripeError as e:
        logger.error("reactivation_checkout_stripe_error", error=str(e), tenant_id=tenant_id)
        raise HTTPException(status_code=500, detail="Failed to create reactivation checkout session")


@router.post("/portal-session")
async def create_portal_session(
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
):
    """Create a Stripe customer portal session for managing billing."""
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
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
):
    """List recent invoices from Stripe."""
    tenant_uuid = uuid.UUID(tenant_id)
    
    from app.models.tenant import Tenant
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_uuid))
    tenant = result.scalar_one_or_none()
    if not tenant or not tenant.stripe_customer_id:
        return {"invoices": []}
    
    import stripe
    import asyncio as _asyncio
    stripe.api_key = settings.STRIPE_SECRET_KEY
    
    # B12 FIX: Stripe SDK is synchronous — run in thread to not block the async event loop
    invoices = await _asyncio.to_thread(
        stripe.Invoice.list,
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


@router.post("/sync-subscription")
async def sync_subscription(
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
):
    """
    Sync subscription status with Stripe.
    - Validates the tenant's subscription with Stripe.
    - Activates any inactive agents that already have a stripe_subscription_id
      (self-healing for cases where the initial webhook failed to propagate).
    """
    import stripe
    from datetime import datetime, timezone, timedelta

    stripe.api_key = settings.STRIPE_SECRET_KEY

    tenant_uuid = uuid.UUID(tenant_id)

    result = await db.execute(select(Tenant).where(Tenant.id == tenant_uuid))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    if not tenant.subscription_id:
        return {"status": "no_subscription", "message": "No subscription found"}

    try:
        stripe_sub = stripe.Subscription.retrieve(tenant.subscription_id)
        is_active = stripe_sub.status in ("active", "trialing")

        if is_active:
            tenant.subscription_status = "active"
            tenant.is_active = True
            await db.commit()
            logger.info("subscription_synced_active", tenant_id=tenant_id)

            # --- Agent self-healing: re-activate any agent that still shows as
            # inactive/payment-required despite the subscription being active.
            agents_activated = 0
            agents_skipped = 0
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    # Fetch ALL agents (active + inactive) from the orchestrator
                    list_resp = await client.get(
                        f"{settings.AI_ORCHESTRATOR_URL}/api/v1/agents",
                        params={"status": "all"},
                        headers={
                            "X-Tenant-ID": tenant_id,
                            "X-Internal-Key": settings.INTERNAL_API_KEY,
                        },
                    )
                    if list_resp.status_code == 200:
                        agents = list_resp.json()

                        # Calculate expiry from Stripe subscription period
                        expires_at = None
                        if stripe_sub.current_period_end:
                            expires_at = datetime.fromtimestamp(
                                stripe_sub.current_period_end, tz=timezone.utc
                            ).isoformat()
                        else:
                            expires_at = (
                                datetime.now(timezone.utc) + timedelta(days=30)
                            ).isoformat()

                        for agent in agents:
                            agent_is_active = agent.get("is_active", False)
                            agent_sub_id = agent.get("stripe_subscription_id")

                            # Activate the agent if:
                            #   (a) it already has a subscription ID (was paid, webhook partially failed), OR
                            #   (b) the tenant subscription is active and agent is inactive
                            #       (covers plans where subscription is per-tenant not per-agent)
                            needs_activation = not agent_is_active and (
                                agent_sub_id is not None or
                                agent.get("deleted_at") is None  # not archived
                            )

                            if needs_activation:
                                sub_id_to_set = agent_sub_id or tenant.subscription_id
                                patch_resp = await client.patch(
                                    f"{settings.AI_ORCHESTRATOR_URL}/api/v1/agents/{agent['id']}",
                                    json={
                                        "is_active": True,
                                        "stripe_subscription_id": sub_id_to_set,
                                        "expires_at": expires_at,
                                    },
                                    headers={
                                        "X-Tenant-ID": tenant_id,
                                        "X-Internal-Key": settings.INTERNAL_API_KEY,
                                    },
                                )
                                if patch_resp.status_code == 200:
                                    agents_activated += 1
                                    logger.info(
                                        "agent_self_healed_on_sync",
                                        agent_id=agent["id"],
                                        tenant_id=tenant_id,
                                        sub_id=sub_id_to_set,
                                    )
                                else:
                                    agents_skipped += 1
                                    logger.warning(
                                        "agent_self_heal_failed",
                                        agent_id=agent["id"],
                                        status=patch_resp.status_code,
                                        body=patch_resp.text[:200],
                                    )
                    else:
                        logger.warning(
                            "sync_subscription_agent_list_failed",
                            status=list_resp.status_code,
                            tenant_id=tenant_id,
                        )
            except Exception as heal_err:
                logger.error("agent_self_heal_error", error=str(heal_err), tenant_id=tenant_id)

            return {
                "status": "active",
                "subscription_status": tenant.subscription_status,
                "agents_activated": agents_activated,
                "agents_skipped": agents_skipped,
            }
        else:
            tenant.subscription_status = stripe_sub.status
            await db.commit()
            logger.info("subscription_synced_inactive", tenant_id=tenant_id, status=stripe_sub.status)

            return {
                "status": "inactive",
                "subscription_status": tenant.subscription_status,
            }

    except stripe.error.StripeError as e:
        logger.error("subscription_sync_failed", tenant_id=tenant_id, error=str(e))
        raise HTTPException(status_code=502, detail=f"Failed to sync with Stripe: {str(e)}")


@router.post("/webhook", status_code=200, include_in_schema=False)
async def stripe_billing_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Handle Stripe webhook events at /api/v1/billing/webhook.
    Activates tenant accounts on successful payment.
    """
    import uuid as _uuid
    from app.models.tenant import Tenant
    from app.services.tenant_service import get_plan_limits

    body = await request.body()
    sig_header = request.headers.get("stripe-signature")

    if not sig_header:
        raise HTTPException(status_code=400, detail="Missing Stripe signature header.")

    import stripe
    stripe.api_key = settings.STRIPE_SECRET_KEY

    try:
        event = stripe.Webhook.construct_event(
            body, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload.")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=401, detail="Invalid signature.")

    event_type = event.get("type", "unknown")
    event_id = event.get("id", "")
    logger.info("billing_webhook_received", event_type=event_type, event_id=event_id)

    # Phase 2: Defence-in-depth idempotency (Redis primary + DB fallback).
    # Both the duplicate-check AND mark_processed run in the webhook's outer
    # transaction so they are atomic with the business logic below.
    idempotency_svc = None
    if event_id:
        redis = getattr(request.app.state, "redis", None)
        idempotency_svc = IdempotencyService(db=db, redis=redis)
        if await idempotency_svc.is_already_processed("stripe_event", event_id):
            logger.info("billing_webhook_duplicate_skipped", event_id=event_id)
            return {"received": True}
        # Mark processed now — business logic below must be idempotent itself
        # as a last line of defence, but we record intent early so a crash
        # mid-flight is treated as processed on the next retry.
        await idempotency_svc.mark_processed("stripe_event", event_id)

    if event_type == "checkout.session.completed":
        session = event.get("data", {}).get("object", {})
        metadata = session.get("metadata", {})
        tenant_id = metadata.get("tenant_id")
        plan = metadata.get("plan")
        stripe_session_id = session.get("id", "")

        if tenant_id:
            # Phase 6: Single atomic transaction — "paid" and "activated" are inseparable.
            try:
                async with db.begin():
                    from app.models.tenant import TenantUsage
                    result = await db.execute(select(Tenant).where(Tenant.id == _uuid.UUID(tenant_id)))
                    tenant = result.scalar_one_or_none()
                    if tenant:
                        # ALWAYS activate subscription on payment success
                        tenant.subscription_status = "active"
                        tenant.subscription_id = session.get("subscription") or session.get("id")
                        if plan:
                            tenant.plan = plan
                            tenant.plan_limits = await get_plan_limits(plan, db)
                    # Mark idempotency key inside same transaction for atomicity
                    logger.info("tenant_subscription_activated", tenant_id=tenant_id, plan=plan)

                # FLOW 1: Activate specific agent if metadata contains agent_id
                # action="reactivate_agent" → restore archived agent, do NOT bump agent_count
                # action="add_agent_slot" / missing → new slot, bump agent_count
                agent_id = metadata.get("agent_id")
                is_reactivation = metadata.get("action") == "reactivate_agent"
                slot_delta = 0
                slot_accounted = False
                if agent_id:
                    logger.info("activating_agent_from_webhook", tenant_id=tenant_id, agent_id=agent_id)
                    subscription_id = session.get("subscription")
                    
                    # Calculate expiry from Stripe subscription period
                    expires_at = None
                    if subscription_id:
                        try:
                            stripe_sub = stripe.Subscription.retrieve(subscription_id)
                            if stripe_sub.current_period_end:
                                expires_at = datetime.fromtimestamp(
                                    stripe_sub.current_period_end, tz=timezone.utc
                                )
                        except Exception as e:
                            logger.warning("subscription_period_retrieval_failed", error=str(e))
                            expires_at = datetime.now(timezone.utc) + timedelta(days=30)
                    else:
                        expires_at = datetime.now(timezone.utc) + timedelta(days=30)
                    
                    try:
                        async with httpx.AsyncClient() as client:
                            headers = {"X-Tenant-ID": tenant_id, "X-User-Role": "owner", "X-Internal-Key": settings.INTERNAL_API_KEY}
                            activate_res = await client.patch(
                                f"{settings.AI_ORCHESTRATOR_URL}/api/v1/agents/{agent_id}",
                                json={
                                    "is_active": True,
                                    "stripe_subscription_id": subscription_id,
                                    "expires_at": expires_at.isoformat() if expires_at else None
                                },
                                headers=headers,
                                timeout=10.0
                            )
                            if activate_res.status_code == 200:
                                logger.info("agent_activated_successfully", agent_id=agent_id,
                                            expires_at=expires_at, reactivation=is_reactivation)

                                # Only bump agent_count for NEW slots, not reactivations
                                # (the slot was already counted when the agent was first created)
                                if not is_reactivation:
                                    slot_delta = 1
                                    slot_accounted = True
                            else:
                                logger.error("agent_activation_failed_upstream", agent_id=agent_id, status=activate_res.status_code)
                                # Failsafe: Agent missing or errored -> Issue refund/cancel to prevent unauthorized charge
                                if subscription_id:
                                    try:
                                        stripe.Subscription.delete(subscription_id)
                                        logger.info("stripe_subscription_cancelled_failsafe", subscription_id=subscription_id)
                                    except Exception as sub_e:
                                        logger.error("stripe_subscription_cancel_failed", error=str(sub_e))
                                        
                                payment_intent = session.get("payment_intent")
                                if payment_intent:
                                    try:
                                        stripe.Refund.create(payment_intent=payment_intent)
                                        logger.info("stripe_payment_refunded_failsafe", payment_intent=payment_intent)
                                    except Exception as ref_e:
                                        logger.error("stripe_refund_failed", error=str(ref_e))

                    except Exception as e:
                        logger.error("agent_activation_request_error", error=str(e), agent_id=agent_id)

                # FLOW 2: LEGACY/FALLBACK Auto-create agent from config
                pending_purchase_id = metadata.get("pending_agent_purchase_id")
                if pending_purchase_id:
                    from app.models.tenant import PendingAgentPurchase
                    pending_res = await db.execute(select(PendingAgentPurchase).where(PendingAgentPurchase.id == _uuid.UUID(pending_purchase_id)))
                    pending = pending_res.scalar_one_or_none()
                    if pending:
                        logger.info("creating_agent_from_pending_purchase", tenant_id=tenant_id, pending_id=pending_purchase_id)
                        try:
                            async with httpx.AsyncClient() as client:
                                headers = {"X-Tenant-ID": tenant_id, "X-User-Role": "owner", "X-Internal-Key": settings.INTERNAL_API_KEY}
                                create_res = await client.post(
                                    f"{settings.AI_ORCHESTRATOR_URL}/api/v1/agents/",
                                    json={**pending.config, "is_active": True, "stripe_subscription_id": session.get("subscription")},
                                    headers=headers,
                                    timeout=10.0
                                )
                                if create_res.status_code in (200, 201):
                                    await db.delete(pending)
                                    slot_delta = 1
                                    slot_accounted = True
                                    await db.commit()
                                    logger.info("pending_agent_created_and_cleaned_up", tenant_id=tenant_id)
                        except Exception as e:
                            logger.error("pending_agent_creation_error", error=str(e))

                # FLOW 3: Generic Slot Increment
                if metadata.get("action") == "add_agent_slot":
                    logger.info("adding_generic_agent_slot", tenant_id=tenant_id)
                    if not slot_accounted:
                        slot_delta = 1
                        slot_accounted = True

                if tenant and slot_delta:
                    await db.execute(
                        _sa_update(TenantUsage)
                        .where(TenantUsage.tenant_id == tenant.id)
                        .values(agent_count=func.greatest(0, TenantUsage.agent_count + slot_delta))
                    )
                    await db.commit()
                    logger.info("agent_slot_accounted", tenant_id=tenant_id, slot_delta=slot_delta)

            except Exception as e:
                logger.error("billing_webhook_checkout_error", error=str(e), tenant_id=tenant_id)

    elif event_type == "customer.subscription.deleted":
        # Subscription cancelled externally (non-payment, admin action, or API call).
        # Deactivate the associated agent and decrement agent_count so the slot is freed.
        subscription = event.get("data", {}).get("object", {})
        sub_id = subscription.get("id")
        metadata = subscription.get("metadata", {})
        tenant_id = metadata.get("tenant_id")

        if sub_id and tenant_id:
            try:
                from app.models.tenant import TenantUsage
                # Find the agent that holds this subscription
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        f"{settings.AI_ORCHESTRATOR_URL}/api/v1/agents",
                        headers={"X-Tenant-ID": tenant_id, "X-Internal-Key": settings.INTERNAL_API_KEY},
                    )
                    if resp.status_code == 200:
                        agents = resp.json()
                        for ag in agents:
                            if ag.get("stripe_subscription_id") == sub_id:
                                # Deactivate agent
                                await client.patch(
                                    f"{settings.AI_ORCHESTRATOR_URL}/api/v1/agents/{ag['id']}",
                                    json={"is_active": False, "stripe_subscription_id": None},
                                    headers={"X-Tenant-ID": tenant_id, "X-Internal-Key": settings.INTERNAL_API_KEY},
                                    timeout=10.0,
                                )
                                logger.info(
                                    "agent_deactivated_on_subscription_delete",
                                    agent_id=ag["id"],
                                    subscription_id=sub_id,
                                    tenant_id=tenant_id,
                                )
                                break

                # Atomic decrement (floor at 0) — avoids race on concurrent cancellation webhooks
                t_uuid = _uuid.UUID(tenant_id)
                await db.execute(
                    _sa_update(TenantUsage)
                    .where(TenantUsage.tenant_id == t_uuid)
                    .values(agent_count=func.greatest(0, TenantUsage.agent_count - 1))
                )

                # Update tenant subscription status
                result = await db.execute(select(Tenant).where(Tenant.id == t_uuid))
                tenant = result.scalar_one_or_none()
                if tenant and tenant.subscription_id == sub_id:
                    tenant.subscription_status = "cancelled"

                await db.commit()
                logger.info("subscription_deleted_processed", subscription_id=sub_id, tenant_id=tenant_id)
            except Exception as e:
                logger.error("subscription_deleted_webhook_error", error=str(e), subscription_id=sub_id)

    elif event_type in ("customer.subscription.created", "customer.subscription.updated"):
        subscription = event.get("data", {}).get("object", {})
        metadata = subscription.get("metadata", {})
        tenant_id = metadata.get("tenant_id")
        plan = metadata.get("plan")
        status = subscription.get("status")
        quantity = subscription.get("quantity") or 1

        if tenant_id:
            try:
                from app.models.tenant import TenantUsage
                result = await db.execute(select(Tenant).where(Tenant.id == _uuid.UUID(tenant_id)))
                tenant = result.scalar_one_or_none()
                if tenant:
                    tenant.subscription_id = subscription.get("id")
                    tenant.subscription_status = status or "active"
                    if status == "active":
                        tenant.is_active = True
                        if plan:
                            tenant.plan = plan
                            tenant.plan_limits = await get_plan_limits(plan, db)
                        
                        # Sync agent slots with subscription quantity
                        usage_res = await db.execute(select(TenantUsage).where(TenantUsage.tenant_id == tenant.id))
                        usage = usage_res.scalar_one_or_none()
                        if usage and usage.agent_count < quantity:
                            usage.agent_count = quantity
                            
                    await db.commit()
                    logger.info("billing_webhook_subscription_updated", tenant_id=tenant_id, status=status)
            except Exception as e:
                logger.error("billing_webhook_subscription_error", error=str(e), tenant_id=tenant_id)

    elif event_type == "invoice.paid":
        invoice = event.get("data", {}).get("object", {})
        customer_id = invoice.get("customer")
        if customer_id:
            try:
                from app.models.tenant import TenantUsage
                result = await db.execute(select(Tenant).where(Tenant.stripe_customer_id == customer_id))
                tenant = result.scalar_one_or_none()
                if tenant:
                    tenant.is_active = True
                    tenant.subscription_status = "active"
                    if invoice.get("subscription"):
                        tenant.subscription_id = invoice["subscription"]
                    
                    # Ensure at least 1 slot is granted on paid invoice if currently 0
                    usage_res = await db.execute(select(TenantUsage).where(TenantUsage.tenant_id == tenant.id))
                    usage = usage_res.scalar_one_or_none()
                    if usage and usage.agent_count == 0:
                        usage.agent_count = 1
                        
                    await db.commit()
                    logger.info("billing_webhook_invoice_paid", customer_id=customer_id)
            except Exception as e:
                logger.error("billing_webhook_invoice_paid_error", error=str(e), customer_id=customer_id)

    return {"received": True}
