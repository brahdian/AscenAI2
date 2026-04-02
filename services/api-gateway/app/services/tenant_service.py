from __future__ import annotations

import uuid
from typing import Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Tenant, TenantUsage

logger = structlog.get_logger(__name__)

# Plan limits definition — single source of truth, aligned with billing.py pricing.
# -1 = unlimited.  Keys match Tenant.plan values.
PLAN_LIMITS: dict[str, dict] = {
    "text_growth": {
        "chats_included": 1_500,
        "max_voice_minutes_per_month": 0,
        "max_agents": 5,
        "max_api_keys": 5,
        "max_webhooks": 5,
        "max_playbooks_per_agent": 5,
        "max_rag_documents": 50,
        "max_team_seats": 5,
    },
    "voice_growth": {
        "chats_included": 3_000,
        "max_voice_minutes_per_month": 600,
        "max_agents": 5,
        "max_api_keys": 5,
        "max_webhooks": 5,
        "max_playbooks_per_agent": 5,
        "max_rag_documents": 50,
        "max_team_seats": 5,
    },
    "voice_business": {
        "chats_included": 7_500,
        "max_voice_minutes_per_month": 1_500,
        "max_agents": 20,
        "max_api_keys": 20,
        "max_webhooks": 20,
        "max_playbooks_per_agent": 100,
        "max_rag_documents": 200,
        "max_team_seats": 20,
    },
    "enterprise": {
        "chats_included": 50_000,
        "max_voice_minutes_per_month": 10_000,
        "max_agents": 500,
        "max_api_keys": 500,
        "max_webhooks": 500,
        "max_playbooks_per_agent": 1_000,
        "max_rag_documents": 10_000,
        "max_team_seats": 500,
    },
}

# Legacy plan name aliases
PLAN_LIMITS["professional"] = PLAN_LIMITS["voice_growth"]
PLAN_LIMITS["business"] = PLAN_LIMITS["voice_business"]
PLAN_LIMITS["starter"] = PLAN_LIMITS["text_growth"]


def get_plan_limits(plan: str) -> dict:
    """Return the limits dict for a plan, defaulting to professional."""
    return PLAN_LIMITS.get(plan, PLAN_LIMITS["professional"])


def check_limit(limit_value: int, current: int) -> bool:
    """Return True when the tenant is within the limit.
    -1 means unlimited and always passes."""
    if limit_value == -1:
        return True
    return current < limit_value


class TenantService:
    async def get_tenant(self, tenant_id: str, db: AsyncSession) -> Optional[Tenant]:
        result = await db.execute(
            select(Tenant).where(Tenant.id == uuid.UUID(tenant_id))
        )
        return result.scalar_one_or_none()

    async def get_tenant_usage(
        self, tenant_id: str, db: AsyncSession
    ) -> Optional[TenantUsage]:
        result = await db.execute(
            select(TenantUsage).where(TenantUsage.tenant_id == uuid.UUID(tenant_id))
        )
        return result.scalar_one_or_none()

    async def update_tenant(
        self, tenant_id: str, updates: dict, db: AsyncSession
    ) -> Tenant:
        from fastapi import HTTPException

        tenant = await self.get_tenant(tenant_id, db)
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found.")

        allowed_fields = {
            "name", "business_name", "business_type", "phone", "address",
            "timezone", "metadata_",
        }
        for field, value in updates.items():
            if field in allowed_fields:
                setattr(tenant, field, value)

        await db.commit()
        await db.refresh(tenant)
        logger.info("tenant_updated", tenant_id=tenant_id)
        return tenant

    async def upgrade_plan(
        self, tenant_id: str, new_plan: str, db: AsyncSession
    ) -> Tenant:
        from fastapi import HTTPException

        if new_plan not in PLAN_LIMITS:
            raise HTTPException(status_code=400, detail=f"Unknown plan: {new_plan}")

        tenant = await self.get_tenant(tenant_id, db)
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found.")

        tenant.plan = new_plan
        tenant.plan_limits = PLAN_LIMITS[new_plan]
        await db.commit()
        await db.refresh(tenant)
        logger.info("tenant_plan_upgraded", tenant_id=tenant_id, plan=new_plan)
        return tenant


tenant_service = TenantService()
