from __future__ import annotations

import uuid
from typing import Optional

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invite import UserInvite
from app.models.tenant import Tenant, TenantUsage
from app.models.user import User

logger = structlog.get_logger(__name__)

# Plan limits definition — fallback default.
DEFAULT_PLAN_LIMITS: dict[str, dict] = {
    "starter": {
        "chats_included": 20_000,
        "max_voice_minutes_per_month": 0,
        "max_agents": 5,
        "max_api_keys": 5,
        "max_webhooks": 5,
        "max_playbooks_per_agent": 5,
        "max_rag_documents": 50,
        "max_team_seats": 5,
    },
    "growth": {
        "chats_included": 80_000,
        "max_voice_minutes_per_month": 1_500,
        "max_agents": 10,
        "max_api_keys": 10,
        "max_webhooks": 10,
        "max_playbooks_per_agent": 10,
        "max_rag_documents": 100,
        "max_team_seats": 10,
    },
    "business": {
        "chats_included": 170_000,
        "max_voice_minutes_per_month": 3_500,
        "max_agents": 25,
        "max_api_keys": 25,
        "max_webhooks": 25,
        "max_playbooks_per_agent": 100,
        "max_rag_documents": 500,
        "max_team_seats": 25,
    },
    "enterprise": {
        "chats_included": 500_000,
        "max_voice_minutes_per_month": 10_000,
        "max_agents": 500,
        "max_api_keys": 500,
        "max_webhooks": 500,
        "max_playbooks_per_agent": 1_000,
        "max_rag_documents": 10_000,
        "max_team_seats": 500,
    },
}


async def get_all_plan_limits(db: AsyncSession) -> dict[str, dict]:
    """Fetch plan limits from platform_settings."""
    try:
        from app.models.platform import PlatformSetting
        result = await db.execute(
            select(PlatformSetting).where(PlatformSetting.key == "plan_limits")
        )
        setting = result.scalar_one_or_none()
        if setting and setting.value:
            return setting.value
    except Exception as e:
        logger.warning("failed_to_fetch_plan_limits", error=str(e))
    return DEFAULT_PLAN_LIMITS


async def get_plan_limits(plan: str, db: AsyncSession) -> dict:
    """Return the limits dict for a plan, defaulting to professional."""
    limits = await get_all_plan_limits(db)
    return limits.get(plan, limits.get("professional", limits.get("voice_growth", {})))


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

        limits = await get_all_plan_limits(db)
        if new_plan not in limits:
            raise HTTPException(status_code=400, detail=f"Unknown plan: {new_plan}")

        tenant = await self.get_tenant(tenant_id, db)
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found.")

        tenant.plan = new_plan
        tenant.plan_limits = await get_plan_limits(new_plan, db)
        await db.commit()
        await db.refresh(tenant)
        logger.info("tenant_plan_upgraded", tenant_id=tenant_id, plan=new_plan)
        return tenant

    async def check_team_seats(self, tenant_id: str, db: AsyncSession) -> bool:
        """Check if the tenant has available seats in their plan.
        Counts both active users and pending (unexpired) invitations.
        """
        tenant = await self.get_tenant(tenant_id, db)
        if not tenant:
            return False

        # Get limits
        limits = tenant.plan_limits or await get_plan_limits(tenant.plan, db)
        max_seats = limits.get("max_team_seats", 5)
        if max_seats == -1:
            return True

        # 1. Count current active users
        user_count_result = await db.execute(
            select(func.count())
            .select_from(User)
            .where(
                User.tenant_id == uuid.UUID(tenant_id),
                User.is_active == True
            )
        )
        active_count = user_count_result.scalar() or 0

        # 2. Count pending invites that haven't expired or been accepted
        #    (Accepted invites become active users, so they are already counted above)
        from datetime import datetime, timezone
        invite_count_result = await db.execute(
            select(func.count())
            .select_from(UserInvite)
            .where(
                UserInvite.tenant_id == uuid.UUID(tenant_id),
                UserInvite.accepted_at == None,
                UserInvite.expires_at > datetime.now(timezone.utc)
            )
        )
        pending_count = invite_count_result.scalar() or 0

        total_occupied = active_count + pending_count
        
        is_allowed = total_occupied < max_seats
        if not is_allowed:
            logger.warning(
                "seat_limit_reached",
                tenant_id=tenant_id,
                total_occupied=total_occupied,
                max_seats=max_seats
            )
        return is_allowed


tenant_service = TenantService()
