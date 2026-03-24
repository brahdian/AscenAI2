from __future__ import annotations

import uuid
from typing import Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Tenant, TenantUsage

logger = structlog.get_logger(__name__)

# Plan limits definition (used by auth_service and tenant routes)
PLAN_LIMITS: dict[str, dict] = {
    "starter": {
        "max_sessions_per_month": 500,
        "max_messages_per_month": 5000,
        "max_tokens_per_month": 1_000_000,
        "max_voice_minutes_per_month": 60,
        "max_agents": 1,
        "max_api_keys": 3,
        "max_webhooks": 2,
    },
    "growth": {
        "max_sessions_per_month": 5000,
        "max_messages_per_month": 50_000,
        "max_tokens_per_month": 10_000_000,
        "max_voice_minutes_per_month": 600,
        "max_agents": 5,
        "max_api_keys": 10,
        "max_webhooks": 10,
    },
    "enterprise": {
        "max_sessions_per_month": -1,  # unlimited
        "max_messages_per_month": -1,
        "max_tokens_per_month": -1,
        "max_voice_minutes_per_month": -1,
        "max_agents": -1,
        "max_api_keys": -1,
        "max_webhooks": -1,
    },
}


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
