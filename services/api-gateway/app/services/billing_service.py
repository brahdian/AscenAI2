"""
Billing Service — Usage tracking, plan enforcement, overage calculation.

Complements the billing API router (app/api.v1.billing) which handles
Stripe checkout / portal / invoice endpoints.

Tracks (Redis-backed, real-time):
  - LLM tokens per tenant per month
  - Voice minutes per tenant per month
  - Tool calls per tenant per month

Enforces:
  - Soft warning at 80 % of quota
  - Hard block at 100 % (configurable per plan)

Calculates:
  - Overage charges aligned with PLAN_LIMITS in tenant_service.py
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import uuid
import stripe
from app.core.config import settings
from app.models.tenant import Tenant
from app.services.tenant_service import get_plan_limits

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Overage rates (per-unit cost beyond included quota)
# ---------------------------------------------------------------------------

_OVERAGE_RATES: dict[str, dict[str, Decimal]] = {
    "text_growth": {
        "per_chat": Decimal("0.002"),
        "per_voice_minute": Decimal("0.10"),
        "per_tool_call": Decimal("0.005"),
    },
    "voice_growth": {
        "per_chat": Decimal("0.002"),
        "per_voice_minute": Decimal("0.10"),
        "per_tool_call": Decimal("0.005"),
    },
    "voice_business": {
        "per_chat": Decimal("0.002"),
        "per_voice_minute": Decimal("0.10"),
        "per_tool_call": Decimal("0.003"),
    },
    "enterprise": {
        "per_chat": Decimal("0.00"),
        "per_voice_minute": Decimal("0.00"),
        "per_tool_call": Decimal("0.00"),
    },
}

# Provide legacy aliases matching PLAN_LIMITS keys
_OVERAGE_RATES["professional"] = _OVERAGE_RATES["voice_growth"]
_OVERAGE_RATES["business"] = _OVERAGE_RATES["voice_business"]
_OVERAGE_RATES["starter"] = _OVERAGE_RATES["text_growth"]

_SOFT_WARNING_PCT = 80  # warn when usage reaches this %


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _month_key() -> str:
    """Return current UTC month key, e.g. '2026-04'."""
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _resolve_plan(plan: str) -> str:
    """Normalise plan aliases to canonical key used in PLAN_LIMITS."""
    aliases = {
        "starter": "text_growth",
        "professional": "voice_growth",
        "business": "voice_business",
    }
    return aliases.get(plan, plan)


def _quantize(value: Decimal) -> float:
    """Convert Decimal to float rounded to 2 decimal places."""
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# BillingService
# ---------------------------------------------------------------------------

class BillingService:
    """Redis-backed real-time usage tracker with plan enforcement."""

    def __init__(self, db: AsyncSession, redis_client) -> None:
        self.db = db
        self.redis = redis_client

    # ------------------------------------------------------------------
    # Usage recording
    # ------------------------------------------------------------------

    async def record_token_usage(
        self,
        tenant_id: str,
        tokens: int,
        session_id: str = "",
    ) -> None:
        """Record LLM token usage for a tenant."""
        key = f"billing:tokens:{tenant_id}:{_month_key()}"
        await self._incr(key, tokens)
        logger.info(
            "token_usage_recorded",
            tenant_id=tenant_id,
            tokens=tokens,
            session_id=session_id,
        )

    async def record_chat_usage(
        self,
        tenant_id: str,
        chat_units: int = 1,
        session_id: str = "",
    ) -> None:
        """Record chat-equivalent units for a tenant."""
        key = f"billing:chats:{tenant_id}:{_month_key()}"
        await self._incr(key, chat_units)
        logger.info(
            "chat_usage_recorded",
            tenant_id=tenant_id,
            chat_units=chat_units,
            session_id=session_id,
        )

    async def record_voice_minutes(
        self,
        tenant_id: str,
        seconds: float,
        session_id: str = "",
    ) -> None:
        """Record voice call duration for a tenant."""
        minutes = seconds / 60.0
        key = f"billing:minutes:{tenant_id}:{_month_key()}"
        await self._incr_float(key, minutes)
        logger.info(
            "voice_minutes_recorded",
            tenant_id=tenant_id,
            seconds=seconds,
            minutes=round(minutes, 2),
        )

    async def record_tool_usage(
        self,
        tenant_id: str,
        tool_name: str,
        success: bool = True,
    ) -> None:
        """Record tool call usage for a tenant."""
        key = f"billing:tools:{tenant_id}:{_month_key()}"
        await self._incr(key, 1)
        logger.info(
            "tool_usage_recorded",
            tenant_id=tenant_id,
            tool_name=tool_name,
            success=success,
        )

    # ------------------------------------------------------------------
    # Usage retrieval
    # ------------------------------------------------------------------

    async def get_usage_summary(
        self,
        tenant_id: str,
        month: Optional[str] = None,
    ) -> dict[str, Any]:
        """Get usage summary for a tenant for the current or specified month."""
        month = month or _month_key()

        tokens = await self._get_int(f"billing:tokens:{tenant_id}:{month}")
        chats = await self._get_int(f"billing:chats:{tenant_id}:{month}")
        minutes = await self._get_float(f"billing:minutes:{tenant_id}:{month}")
        tool_calls = await self._get_int(f"billing:tools:{tenant_id}:{month}")

        return {
            "tenant_id": tenant_id,
            "month": month,
            "tokens": tokens,
            "chats": chats,
            "voice_minutes": round(minutes, 2),
            "tool_calls": tool_calls,
        }

    # ------------------------------------------------------------------
    # Plan limit enforcement
    # ------------------------------------------------------------------

    async def check_limits(
        self,
        tenant_id: str,
        plan: str = "voice_growth",
    ) -> dict[str, Any]:
        """Check if tenant is within plan limits.

        Returns usage percentages, warnings (soft), and blocked flag (hard).
        """
        canonical = _resolve_plan(plan)
        limits = await get_plan_limits(canonical, self.db)
        usage = await self.get_usage_summary(tenant_id)

        chats_limit = limits.get("chats_included", 0) or 0
        minutes_limit = limits.get("max_voice_minutes_per_month", 0) or 0
        tool_limit = limits.get("max_tool_calls_per_month", 10_000)

        chat_pct = (usage["chats"] / chats_limit * 100) if chats_limit else 0
        minute_pct = (usage["voice_minutes"] / minutes_limit * 100) if minutes_limit else 0
        tool_pct = (usage["tool_calls"] / tool_limit * 100) if tool_limit else 0

        warnings: list[str] = []
        blocked = False

        for label, pct, limit_val in [
            ("Chats", chat_pct, chats_limit),
            ("Voice minutes", minute_pct, minutes_limit),
            ("Tool calls", tool_pct, tool_limit),
        ]:
            if limit_val and limit_val > 0:
                if pct >= 100:
                    warnings.append(f"{label} limit exceeded")
                    blocked = True
                elif pct >= _SOFT_WARNING_PCT:
                    warnings.append(f"{label} usage at {pct:.0f}%")

        return {
            "tenant_id": tenant_id,
            "plan": canonical,
            "usage": usage,
            "limits": {
                "chats": chats_limit,
                "voice_minutes": minutes_limit,
                "tool_calls": tool_limit,
            },
            "percentages": {
                "chats": round(chat_pct, 1),
                "voice_minutes": round(minute_pct, 1),
                "tool_calls": round(tool_pct, 1),
            },
            "warnings": warnings,
            "blocked": blocked,
        }

    async def allow_request(
        self,
        tenant_id: str,
        plan: str = "voice_growth",
    ) -> bool:
        """Return True if the tenant is allowed to make another request."""
        result = await self.check_limits(tenant_id, plan)
        return not result["blocked"]

    # ------------------------------------------------------------------
    # Overage calculation
    # ------------------------------------------------------------------

    async def calculate_overage(
        self,
        tenant_id: str,
        plan: str = "voice_growth",
    ) -> dict[str, Any]:
        """Calculate overage charges for the current month."""
        canonical = _resolve_plan(plan)
        limits = await get_plan_limits(canonical, self.db)
        rates = _OVERAGE_RATES.get(canonical, _OVERAGE_RATES["professional"])
        usage = await self.get_usage_summary(tenant_id)

        chats_limit = limits.get("chats_included", 0) or 0
        minutes_limit = limits.get("max_voice_minutes_per_month", 0) or 0
        tool_limit = limits.get("max_tool_calls_per_month", 10_000)

        chat_overage = max(0, usage["chats"] - chats_limit)
        minute_overage = max(0, usage["voice_minutes"] - minutes_limit)
        tool_overage = max(0, usage["tool_calls"] - tool_limit)

        chat_charge = Decimal(str(chat_overage)) * rates["per_chat"]
        minute_charge = Decimal(str(minute_overage)) * rates["per_voice_minute"]
        tool_charge = Decimal(str(tool_overage)) * rates["per_tool_call"]

        total_overage = chat_charge + minute_charge + tool_charge

        return {
            "tenant_id": tenant_id,
            "plan": canonical,
            "month": _month_key(),
            "overage": {
                "chats": {
                    "overage_count": chat_overage,
                    "charge": _quantize(chat_charge),
                },
                "voice_minutes": {
                    "overage_count": round(minute_overage, 2),
                    "charge": _quantize(minute_charge),
                },
                "tool_calls": {
                    "overage_count": tool_overage,
                    "charge": _quantize(tool_charge),
                },
            },
            "total_overage": _quantize(total_overage),
        }

    # ------------------------------------------------------------------
    # Invoice generation
    # ------------------------------------------------------------------

    async def generate_invoice(
        self,
        tenant_id: str,
        plan: str = "voice_growth",
        base_price: Optional[float] = None,
    ) -> dict[str, Any]:
        """Generate a draft invoice summary for the current month."""
        canonical = _resolve_plan(plan)
        overage_data = await self.calculate_overage(tenant_id, canonical)

        if base_price is None:
            plan_config = _OVERAGE_RATES.get(canonical, {})
            base_price = 0.0  # caller should supply from Tenant / Stripe

        total = round(base_price + overage_data["total_overage"], 2)

        return {
            "tenant_id": tenant_id,
            "month": _month_key(),
            "plan": canonical,
            "line_items": [
                {
                    "description": f"Base subscription ({canonical})",
                    "amount": base_price,
                },
                {
                    "description": "Chat overage",
                    "amount": overage_data["overage"]["chats"]["charge"],
                },
                {
                    "description": "Voice minute overage",
                    "amount": overage_data["overage"]["voice_minutes"]["charge"],
                },
                {
                    "description": "Tool call overage",
                    "amount": overage_data["overage"]["tool_calls"]["charge"],
                },
            ],
            "subtotal": base_price,
            "overage_total": overage_data["total_overage"],
            "total": total,
            "currency": "usd",
            "status": "draft",
        }

    # ------------------------------------------------------------------
    # Stripe helpers (thin wrappers for metered billing)
    # ------------------------------------------------------------------

    async def report_usage_to_stripe(
        self,
        subscription_item_id: str,
        quantity: int,
    ) -> dict[str, Any]:
        """Report metered usage to Stripe."""
        try:
            import stripe
            from app.core.config import settings

            stripe.api_key = settings.STRIPE_SECRET_KEY
            usage_record = stripe.SubscriptionItem.create_usage_record(
                subscription_item_id,
                quantity=quantity,
                timestamp=int(time.time()),
                action="increment",
            )
            return {"id": usage_record.id, "status": "recorded"}
        except ImportError:
            logger.warning("stripe_not_installed")
            return {"status": "stripe_unavailable"}
        except Exception as exc:
            logger.warning("stripe_usage_report_error", error=str(exc))
            return {"status": "error", "detail": str(exc)}

    # ------------------------------------------------------------------
    # Internal Redis helpers
    # ------------------------------------------------------------------

    async def _incr(self, key: str, amount: int) -> None:
        if not self.redis:
            return
        try:
            await self.redis.incrby(key, amount)
            await self.redis.expire(key, 86400 * 32)
        except Exception as exc:
            logger.warning("billing_redis_error", key=key, error=str(exc))

    async def _incr_float(self, key: str, amount: float) -> None:
        if not self.redis:
            return
        try:
            await self.redis.incrbyfloat(key, amount)
            await self.redis.expire(key, 86400 * 32)
        except Exception as exc:
            logger.warning("billing_redis_error", key=key, error=str(exc))

    async def _get_int(self, key: str) -> int:
        if not self.redis:
            return 0
        try:
            val = await self.redis.get(key)
            return int(val) if val else 0
        except Exception:
            return 0

    async def _get_float(self, key: str) -> float:
        if not self.redis:
            return 0.0
        try:
            val = await self.redis.get(key)
            return float(val) if val else 0.0
        except Exception:
            return 0.0


# ---------------------------------------------------------------------------
# DB-backed usage summary (falls back when Redis is empty)
# ---------------------------------------------------------------------------

async def get_db_usage_summary(tenant_id: str, db: AsyncSession) -> dict[str, Any]:
    """Fetch usage from the TenantUsage table (authoritative monthly counters)."""
    import uuid as _uuid
    from app.models.tenant import TenantUsage

    result = await db.execute(
        select(TenantUsage).where(TenantUsage.tenant_id == _uuid.UUID(tenant_id))
    )
    row = result.scalar_one_or_none()

    if not row:
        return {
            "tenant_id": tenant_id,
            "sessions": 0,
            "messages": 0,
            "chats": 0,
            "tokens": 0,
            "voice_minutes": 0.0,
            "agent_count": 0,
        }

    return {
        "tenant_id": tenant_id,
        "sessions": row.current_month_sessions or 0,
        "messages": row.current_month_messages or 0,
        "chats": row.current_month_chat_units or 0,
        "tokens": row.current_month_tokens or 0,
        "voice_minutes": float(row.current_month_voice_minutes or 0),
        "agent_count": row.agent_count or 0,
    }

# ---------------------------------------------------------------------------
# Checkout Sessions
# ---------------------------------------------------------------------------

async def create_agent_checkout_session(
    tenant_id: str,
    agent_id: str,
    db: AsyncSession,
    requested_plan: str = None,
    return_path: str = "/dashboard/agents",
) -> str:
    """
    Create a Stripe checkout session for a specific agent.
    Forces monthly subscription mode.
    """
    import uuid as _uuid
    from fastapi import HTTPException
    tenant_uuid = _uuid.UUID(tenant_id)
    
    # 1. Load Tenant
    tenant_result = await db.execute(select(Tenant).where(Tenant.id == tenant_uuid))
    tenant = tenant_result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # 2. Get Pricing (Default to $99/agent if not found)
    from app.api.v1.billing import _get_plan
    target_plan = requested_plan or tenant.plan or "growth"
    plan_data = await _get_plan(target_plan, db)
    price = plan_data.get("price_per_agent") or 99.00

    # 3. Stripe Setup
    stripe.api_key = settings.STRIPE_SECRET_KEY
    
    # Self-healing customer ID
    if not tenant.stripe_customer_id:
        from app.models.user import User
        user_res = await db.execute(select(User).where(User.tenant_id == tenant.id, User.role == "owner"))
        owner = user_res.scalar_one_or_none()
        if owner:
            from app.services.auth_service import _create_stripe_customer
            stripe_customer_id = await _create_stripe_customer(tenant, owner)
            if stripe_customer_id:
                tenant.stripe_customer_id = stripe_customer_id
                await db.commit()

    try:
        kwargs = {
            "payment_method_types": ["card"],
            "line_items": [
                {
                    "price_data": {
                        "currency": "usd",
                        "unit_amount": int(price * 100),
                        "recurring": {"interval": "month"},
                        "product_data": {
                            "name": "AI Agent Subscription",
                            "description": f"Standard {plan_data.get('display_name', 'Professional')} AI Agent",
                        },
                    },
                    "quantity": 1,
                }
            ],
            "mode": "subscription",
            "success_url": f"{settings.FRONTEND_URL}{return_path}?success=true&agent_id={agent_id}",
            "cancel_url": f"{settings.FRONTEND_URL}{return_path}?cancelled=true",
            "metadata": {
                "tenant_id": str(tenant.id),
                "agent_id": agent_id,
                "plan": target_plan,
                "action": "activate_agent",
            },
        }
        if tenant.stripe_customer_id:
            kwargs["customer"] = tenant.stripe_customer_id
        else:
            kwargs["customer_email"] = tenant.email

        checkout_session = stripe.checkout.Session.create(**kwargs)
        return checkout_session.url
    except stripe.error.StripeError as e:
        logger.error("stripe_agent_checkout_error", error=str(e), tenant_id=tenant_id, agent_id=agent_id)
        raise HTTPException(status_code=500, detail=f"Stripe error: {str(e)}")
    except Exception as e:
        logger.error("unexpected_agent_checkout_error", error=str(e), tenant_id=tenant_id, agent_id=agent_id)
        raise HTTPException(status_code=500, detail="An error occurred while initiating purchase.")
