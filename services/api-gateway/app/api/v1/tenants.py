from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_tenant_db, get_current_tenant
from app.services.tenant_service import tenant_service

router = APIRouter(prefix="/tenants")


class TenantUpdateRequest(BaseModel):
    name: str | None = None
    business_name: str | None = None
    business_type: str | None = None
    phone: str | None = None
    address: dict | None = None
    timezone: str | None = None
    metadata_: dict | None = Field(None, alias="metadata")


class TenantResponse(BaseModel):
    id: str
    name: str
    slug: str
    business_type: str
    business_name: str
    email: str
    phone: str
    address: dict
    timezone: str
    plan: str
    plan_display_name: str
    plan_limits: dict
    metadata_: dict = Field(default_factory=dict, alias="metadata")
    is_active: bool

    model_config = {"from_attributes": True, "populate_by_name": True}


class TenantUsageResponse(BaseModel):
    tenant_id: str
    current_month_sessions: int
    current_month_messages: int
    current_month_tokens: int
    current_month_chat_units: int
    current_month_voice_minutes: float
    total_cost_usd: float
    last_reset_at: str

    model_config = {"from_attributes": True}


def _require_tenant(request: Request) -> str:
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return tenant_id


def _require_owner_or_admin(request: Request) -> str:
    tenant_id = _require_tenant(request)
    role = getattr(request.state, "role", "viewer")
    if role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Owner or admin role required.")
    return tenant_id


@router.get("/me", response_model=TenantResponse)
async def get_my_tenant(
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
):
    """Get current tenant details."""
    tenant = await tenant_service.get_tenant(tenant_id, db)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found.")
    return TenantResponse(
        id=str(tenant.id),
        name=tenant.name,
        slug=tenant.slug,
        business_type=tenant.business_type,
        business_name=tenant.business_name,
        email=tenant.email,
        phone=tenant.phone,
        address=tenant.address,
        timezone=tenant.timezone,
        plan=tenant.plan or "",
        plan_display_name=tenant.plan_display_name or "",
        plan_limits=tenant.plan_limits or {},
        metadata_=tenant.metadata_ or {},
        is_active=tenant.is_active,
    )

@router.patch("/me", response_model=TenantResponse)
async def update_my_tenant(
    body: TenantUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
):
    """Update current tenant details (owner/admin only)."""
    tenant_id = _require_owner_or_admin(request)
    updates = body.model_dump(exclude_unset=True, by_alias=False)
    tenant = await tenant_service.update_tenant(tenant_id, updates, db)
    return TenantResponse(
        id=str(tenant.id),
        name=tenant.name,
        slug=tenant.slug,
        business_type=tenant.business_type,
        business_name=tenant.business_name,
        email=tenant.email,
        phone=tenant.phone,
        address=tenant.address,
        timezone=tenant.timezone,
        plan=tenant.plan,
        plan_display_name=tenant.plan_display_name,
        plan_limits=tenant.plan_limits,
        metadata_=tenant.metadata_,
        is_active=tenant.is_active,
    )


@router.get("/me/usage", response_model=TenantUsageResponse)
async def get_my_usage(
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
):
    """Get current tenant usage statistics."""
    usage = await tenant_service.get_tenant_usage(tenant_id, db)
    if not usage:
        raise HTTPException(status_code=404, detail="Usage data not found.")
    return TenantUsageResponse(
        tenant_id=str(usage.tenant_id),
        current_month_sessions=usage.current_month_sessions,
        current_month_messages=usage.current_month_messages,
        current_month_tokens=usage.current_month_tokens,
        current_month_chat_units=usage.current_month_chat_units,
        current_month_voice_minutes=usage.current_month_voice_minutes,
        total_cost_usd=usage.total_cost_usd,
        last_reset_at=usage.last_reset_at.isoformat(),
    )
