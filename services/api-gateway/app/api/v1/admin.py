"""
Admin API — Platform administration endpoints.

Endpoints:
- GET  /admin/tenants                    — List all tenants
- GET  /admin/tenants/{id}               — Get tenant details
- POST /admin/tenants/{id}/suspend       — Suspend tenant
- POST /admin/tenants/{id}/reactivate    — Reactivate tenant
- DELETE /admin/tenants/{id}             — Delete tenant
- GET  /admin/users                      — List users
- PUT  /admin/users/{id}/role            — Update user role
- GET  /admin/prompts                    — Get system prompts
- PUT  /admin/prompts/{agent_id}         — Update system prompt
- GET  /admin/traces                     — Get conversation traces
- GET  /admin/metrics                    — Get platform metrics
- GET  /admin/roles                      — List available roles
"""

from __future__ import annotations

from typing import Optional, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.admin_service import AdminService, get_all_roles

router = APIRouter(prefix="/admin")


def _require_super_admin(request: Request) -> str:
    """Require super_admin role."""
    role = getattr(request.state, "role", "")
    if role != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin access required.")
    return getattr(request.state, "user_id", "")


def _require_admin(request: Request) -> tuple[str, str]:
    """Require admin or super_admin role."""
    role = getattr(request.state, "role", "")
    if role not in ("super_admin", "tenant_owner", "tenant_admin"):
        raise HTTPException(status_code=403, detail="Admin access required.")
    user_id = getattr(request.state, "user_id", "")
    tenant_id = getattr(request.state, "tenant_id", "")
    return user_id, tenant_id


def _get_admin_service(request: Request, db: AsyncSession) -> AdminService:
    """Build AdminService from request-scoped dependencies."""
    redis = request.app.state.redis
    return AdminService(db, redis)


@router.get("/tenants")
async def list_tenants(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    status: str = "",
    db: AsyncSession = Depends(get_db),
):
    """List all tenants (super_admin only)."""
    _require_super_admin(request)
    service = _get_admin_service(request, db)
    return await service.list_tenants(page, per_page, status)


@router.get("/tenants/{tenant_id}")
async def get_tenant_details(
    tenant_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Get detailed tenant information."""
    _require_super_admin(request)
    service = _get_admin_service(request, db)
    return await service.get_tenant_details(tenant_id)


class SuspendRequest(BaseModel):
    reason: str = Field(..., description="Reason for suspension")


@router.post("/tenants/{tenant_id}/suspend")
async def suspend_tenant(
    tenant_id: str,
    body: SuspendRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Suspend a tenant."""
    admin_user_id = _require_super_admin(request)
    service = _get_admin_service(request, db)
    return await service.suspend_tenant(tenant_id, body.reason, admin_user_id)


@router.post("/tenants/{tenant_id}/reactivate")
async def reactivate_tenant(
    tenant_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Reactivate a suspended tenant."""
    admin_user_id = _require_super_admin(request)
    service = _get_admin_service(request, db)
    return await service.reactivate_tenant(tenant_id, admin_user_id)


@router.delete("/tenants/{tenant_id}")
async def delete_tenant(
    tenant_id: str,
    request: Request,
    hard_delete: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """Delete a tenant (soft or hard delete)."""
    admin_user_id = _require_super_admin(request)
    service = _get_admin_service(request, db)
    return await service.delete_tenant(tenant_id, admin_user_id, hard_delete)


@router.get("/users")
async def list_users(
    request: Request,
    tenant_id: str = "",
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """List users."""
    _require_super_admin(request)
    service = _get_admin_service(request, db)
    return await service.list_users(tenant_id, page, per_page)


class RoleUpdateRequest(BaseModel):
    role: str = Field(..., description="New role")


@router.put("/users/{user_id}/role")
async def update_user_role(
    user_id: str,
    body: RoleUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Update a user's role."""
    admin_user_id = _require_super_admin(request)
    service = _get_admin_service(request, db)
    return await service.update_user_role(user_id, body.role, admin_user_id)


@router.get("/prompts")
async def get_system_prompts(
    request: Request,
    agent_id: str = "",
    db: AsyncSession = Depends(get_db),
):
    """Get system prompts."""
    _require_admin(request)
    service = _get_admin_service(request, db)
    return await service.get_system_prompts(agent_id)


class PromptUpdateRequest(BaseModel):
    system_prompt: str = Field(..., description="New system prompt")


@router.put("/prompts/{agent_id}")
async def update_system_prompt(
    agent_id: str,
    body: PromptUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Update an agent's system prompt."""
    admin_user_id, _ = _require_admin(request)
    service = _get_admin_service(request, db)
    return await service.update_system_prompt(agent_id, body.system_prompt, admin_user_id)


@router.get("/traces")
async def get_traces(
    request: Request,
    session_id: str = "",
    tenant_id: str = "",
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """Get conversation traces (redacted)."""
    _require_admin(request)
    service = _get_admin_service(request, db)
    return await service.get_traces(session_id, tenant_id, limit)


@router.get("/metrics")
async def get_platform_metrics(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Get platform-wide metrics."""
    _require_super_admin(request)
    service = _get_admin_service(request, db)
    return await service.get_platform_metrics()


@router.get("/roles")
async def list_roles(db: AsyncSession = Depends(get_db)):
    """List available roles and their permissions."""
    roles = await get_all_roles(db)
    return {"roles": roles}


@router.get("/settings")
async def get_platform_settings(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Get all platform settings (super_admin only)."""
    _require_super_admin(request)
    service = _get_admin_service(request, db)
    return await service.get_platform_settings()


class SettingUpdateRequest(BaseModel):
    value: Any = Field(..., description="New setting value (JSON serializable)")


@router.put("/settings/{key}")
async def update_platform_setting(
    key: str,
    body: SettingUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Update a platform setting (super_admin only)."""
    admin_user_id = _require_super_admin(request)
    service = _get_admin_service(request, db)
    return await service.update_platform_setting(key, body.value, admin_user_id)


class TrialTenantCreateRequest(BaseModel):
    name: str = Field(..., description="Tenant name (slug)")
    business_name: str = Field(..., description="Business display name")
    plan: str = Field(default="starter", description="Plan tier")
    admin_email: str = Field(..., description="Admin user email")
    admin_password: str = Field(..., description="Admin user password")


@router.post("/trial-tenants")
async def create_trial_tenant(
    body: TrialTenantCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Create a trial tenant with admin user (bypasses Stripe/payment)."""
    admin_user_id = _require_super_admin(request)
    service = _get_admin_service(request, db)
    return await service.create_trial_tenant(
        name=body.name,
        business_name=body.business_name,
        plan=body.plan,
        admin_email=body.admin_email,
        admin_password=body.admin_password,
        created_by=admin_user_id,
    )


@router.get("/tenants/usage")
async def get_all_tenants_usage(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Get usage stats for all tenants (LLM, STT, TTS tokens)."""
    admin_user_id = _require_super_admin(request)
    service = _get_admin_service(request, db)
    return await service.get_all_tenants_usage()
