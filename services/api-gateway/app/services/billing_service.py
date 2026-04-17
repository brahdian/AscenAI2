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
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

import stripe
import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.tenant import Tenant
from app.services.tenant_service import get_plan_limits

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Overage rates — fallback defaults (authoritative values live in PlatformSetting
# "billing_plans" managed via the admin portal at /admin/settings/plans).
# These constants are ONLY used when the DB is unreachable or the plan has no
# overage config. Update them only when first bootstrapping a new environment.
# ---------------------------------------------------------------------------

_DEFAULT_OVERAGE_RATES: dict[str, dict[str, Decimal]] = {
    "starter": {
        "per_chat": Decimal("0.002"),
        "per_voice_minute": Decimal("0.10"),
        "per_tool_call": Decimal("0.005"),
    },
    "growth": {
        "per_chat": Decimal("0.002"),
        "per_voice_minute": Decimal("0.10"),
        "per_tool_call": Decimal("0.005"),
    },
    "business": {
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

_SOFT_WARNING_PCT = settings.QUOTA_SOFT_WARNING_PCT  # configurable via env / admin


async def _get_overage_rates(
    plan: str, db: AsyncSession
) -> dict[str, Decimal]:
    """
    Return per-unit overage rates for *plan*.

    Priority:
    1. billing_plans PlatformSetting (admin-managed, authoritative)
    2. _DEFAULT_OVERAGE_RATES fallback (startup bootstrap)
    """
    try:
        from app.models.platform import PlatformSetting
        from sqlalchemy import select as _sel
        result = await db.execute(
            _sel(PlatformSetting).where(PlatformSetting.key == "billing_plans")
        )
        setting = result.scalar_one_or_none()
        if setting and setting.value:
            # Plan key normalisation: strip prefix e.g. "voice_growth" → check "growth"
            clean = plan.split("_")[-1] if "_" in plan else plan
            plan_cfg = setting.value.get(plan) or setting.value.get(clean) or {}
            if plan_cfg:
                return {
                    "per_chat": Decimal(
                        str(plan_cfg.get("overage_per_chat_equivalent", "0.002"))
                    ),
                    "per_voice_minute": Decimal(
                        str(plan_cfg.get("overage_per_voice_minute", "0.10"))
                    ),
                    "per_tool_call": Decimal(
                        str(plan_cfg.get("overage_per_tool_call", "0.005"))
                    ),
                }
    except Exception as e:
        logger.warning("overage_rate_db_lookup_failed", plan=plan, error=str(e))

    resolved = _resolve_plan(plan)
    return (
        _DEFAULT_OVERAGE_RATES.get(resolved)
        or _DEFAULT_OVERAGE_RATES.get(plan)
        or _DEFAULT_OVERAGE_RATES["voice_growth"]
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _month_key() -> str:
    """Return current UTC month key, e.g. '2026-04'."""
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _resolve_plan(plan: str) -> str:
    """Normalise plan aliases to canonical key used in PLAN_LIMITS."""
    # Standardized plans: starter, growth, business, enterprise
    return plan


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
        # In-memory buffer for Redis increment operations that failed due to
        # transient errors (HIGH-4 fix).  Flushed on the next successful write.
        # This prevents quota counters from silently drifting during short outages.
        self._pending_incr: list[tuple[str, float]] = []

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
        month = _month_key()
        key = f"billing:tokens:{tenant_id}:{month}"
        await self._incr(key, tokens)
        await self._persist_event(tenant_id, "token", tokens, month, session_id)
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
        month = _month_key()
        key = f"billing:chats:{tenant_id}:{month}"
        await self._incr(key, chat_units)
        await self._persist_event(tenant_id, "chat", chat_units, month, session_id)
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
        month = _month_key()
        key = f"billing:minutes:{tenant_id}:{month}"
        await self._incr_float(key, minutes)
        await self._persist_event(tenant_id, "voice_minute", minutes, month, session_id)
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
        month = _month_key()
        key = f"billing:tools:{tenant_id}:{month}"
        await self._incr(key, 1)
        await self._persist_event(tenant_id, "tool_call", 1, month)
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
        """Get usage summary for a tenant for the current or specified month.

        Read strategy (BLOCKER-3 fix):
          1. Try Redis first (fast, real-time running totals).
          2. If Redis returns zero for ALL metrics (cold cache after flush/restart),
             fall back to summing the durable billing_events table in Postgres.
          3. On fallback hit, back-fill Redis so subsequent calls are fast again.
        """
        month = month or _month_key()

        tokens = await self._get_int(f"billing:tokens:{tenant_id}:{month}")
        chats = await self._get_int(f"billing:chats:{tenant_id}:{month}")
        minutes = await self._get_float(f"billing:minutes:{tenant_id}:{month}")
        tool_calls = await self._get_int(f"billing:tools:{tenant_id}:{month}")

        # If all Redis values are zero AND a DB is available, check the durable log.
        # A genuinely zero-usage tenant will re-query the DB each time, which is
        # acceptable because the DB query is fast (indexed on tenant_id + month_key).
        if tokens == 0 and chats == 0 and minutes == 0.0 and tool_calls == 0 and self.db is not None:
            try:
                result = await self.db.execute(
                    text("""
                        SELECT
                            COALESCE(SUM(CASE WHEN event_type = 'token'        THEN amount ELSE 0 END), 0) AS tokens,
                            COALESCE(SUM(CASE WHEN event_type = 'chat'         THEN amount ELSE 0 END), 0) AS chats,
                            COALESCE(SUM(CASE WHEN event_type = 'voice_minute' THEN amount ELSE 0 END), 0) AS minutes,
                            COALESCE(SUM(CASE WHEN event_type = 'tool_call'    THEN amount ELSE 0 END), 0) AS tool_calls
                        FROM billing_events
                        WHERE tenant_id = :tenant_id AND month_key = :month
                    """),
                    {"tenant_id": tenant_id, "month": month},
                )
                row = result.one()
                db_tokens = int(row.tokens or 0)
                db_chats = int(row.chats or 0)
                db_minutes = float(row.minutes or 0.0)
                db_tool_calls = int(row.tool_calls or 0)

                if db_tokens or db_chats or db_minutes or db_tool_calls:
                    # Back-fill Redis so quota enforcement is immediately accurate
                    tokens, chats, minutes, tool_calls = db_tokens, db_chats, db_minutes, db_tool_calls
                    _ttl = 86400 * 32
                    if self.redis:
                        try:
                            pipe = self.redis.pipeline()
                            if db_tokens:
                                pipe.set(f"billing:tokens:{tenant_id}:{month}", db_tokens, ex=_ttl)
                            if db_chats:
                                pipe.set(f"billing:chats:{tenant_id}:{month}", db_chats, ex=_ttl)
                            if db_minutes:
                                pipe.set(f"billing:minutes:{tenant_id}:{month}", db_minutes, ex=_ttl)
                            if db_tool_calls:
                                pipe.set(f"billing:tools:{tenant_id}:{month}", db_tool_calls, ex=_ttl)
                            await pipe.execute()
                            logger.info(
                                "billing_redis_backfilled_from_db",
                                tenant_id=tenant_id,
                                month=month,
                            )
                        except Exception as exc:
                            logger.warning("billing_redis_backfill_failed", error=str(exc))
            except Exception as exc:
                logger.warning("billing_db_fallback_failed", tenant_id=tenant_id, error=str(exc))

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
        rates = await _get_overage_rates(canonical, self.db)
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
            plan_config = _DEFAULT_OVERAGE_RATES.get(canonical, {})
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

    async def _flush_pending(self) -> None:
        """Replay any buffered increments that failed during a previous Redis error."""
        if not self._pending_incr or not self.redis:
            return
        flushed: list[tuple[str, float]] = []
        still_pending: list[tuple[str, float]] = []
        for pending_key, pending_amount in self._pending_incr:
            try:
                await self.redis.incrbyfloat(pending_key, pending_amount)
                await self.redis.expire(pending_key, 86400 * 32)
                flushed.append((pending_key, pending_amount))
            except Exception:
                still_pending.append((pending_key, pending_amount))
        self._pending_incr = still_pending
        if flushed:
            logger.info("billing_redis_pending_flushed", count=len(flushed))

    async def _incr(self, key: str, amount: int) -> None:
        if not self.redis:
            return
        await self._flush_pending()
        try:
            await self.redis.incrby(key, amount)
            await self.redis.expire(key, 86400 * 32)
        except Exception as exc:
            logger.warning("billing_redis_error_buffered", key=key, error=str(exc))
            self._pending_incr.append((key, float(amount)))

    async def _incr_float(self, key: str, amount: float) -> None:
        if not self.redis:
            return
        await self._flush_pending()
        try:
            await self.redis.incrbyfloat(key, amount)
            await self.redis.expire(key, 86400 * 32)
        except Exception as exc:
            logger.warning("billing_redis_error_buffered", key=key, error=str(exc))
            self._pending_incr.append((key, amount))

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

    # ------------------------------------------------------------------
    # BLOCKER-3: Durable Postgres event log
    # ------------------------------------------------------------------

    async def _persist_event(
        self,
        tenant_id: str,
        event_type: str,
        amount: float,
        month_key: str,
        session_id: str = "",
    ) -> None:
        """Write a durable billing event to Postgres.

        This is the authoritative record used for reconciliation when Redis is
        flushed, restarted, or evicted.  Failures are logged but never raised —
        the Redis write already happened and blocking the caller would be worse.
        """
        if self.db is None:
            return
        try:
            await self.db.execute(
                text(
                    "INSERT INTO billing_events "
                    "(id, tenant_id, event_type, amount, month_key, session_id, created_at) "
                    "VALUES (:id, :tenant_id, :event_type, :amount, :month_key, :session_id, :now)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "tenant_id": tenant_id,
                    "event_type": event_type,
                    "amount": amount,
                    "month_key": month_key,
                    "session_id": session_id or "",
                    "now": datetime.now(timezone.utc),
                },
            )
            # Flush (not commit) — outer request transaction commits later.
            # If there is no outer transaction the autocommit mode handles it.
            await self.db.flush()
        except Exception as exc:
            logger.warning(
                "billing_event_db_persist_failed",
                event_type=event_type,
                tenant_id=tenant_id,
                error=str(exc),
            )


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
    frontend_url: str | None = None,
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
            "success_url": f"{frontend_url or settings.FRONTEND_URL}/dashboard/agents/new?success=true&agent_id={agent_id}",
            "cancel_url": f"{frontend_url or settings.FRONTEND_URL}/dashboard/agents/new?cancelled=true",
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
