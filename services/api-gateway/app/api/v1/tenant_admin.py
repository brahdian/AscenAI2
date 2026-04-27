"""
Tenant Admin Portal API
=======================
Management plane for AscenAI tenants — handles RBAC, billing seat management,
CRM workspace management, and org settings.

Served at: admin.lvh.me → /tenant-admin/*

Access control: owner role OR can_access_admin=true in tenant_members.
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import generate_internal_token, get_current_tenant, get_tenant_db
from app.models.tenant import Tenant, TenantCRMWorkspace, TenantMember, TenantUsage
from app.models.user import User
from app.services.audit_service import audit_log
from app.services.crm_service import crm_service

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/tenant-admin")


# ─── Auth helpers ──────────────────────────────────────────────────────────────

def _require_admin(request: Request) -> tuple[str, str, str]:
    """Returns (tenant_id, user_id, role). Raises 403 if not admin-capable."""
    tenant_id = getattr(request.state, "tenant_id", None)
    user_id = getattr(request.state, "user_id", None)
    role = getattr(request.state, "role", "viewer")
    if not tenant_id or not user_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    if role not in ("owner", "admin", "super_admin"):
        raise HTTPException(status_code=403, detail="Admin access required.")
    return tenant_id, user_id, role


# ─── Schemas ───────────────────────────────────────────────────────────────────

class MemberPermissionsUpdate(BaseModel):
    can_access_agents: Optional[bool] = None
    can_access_crm: Optional[bool] = None
    can_access_billing: Optional[bool] = None
    can_access_admin: Optional[bool] = None
    agents_role: Optional[str] = None
    crm_role: Optional[str] = None
    crm_workspace_id: Optional[str] = None


class InviteMemberRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(default="", max_length=255)
    agents_role: str = Field(default="viewer")
    can_access_crm: bool = False
    crm_role: str = Field(default="viewer")
    crm_workspace_id: Optional[str] = None
    is_crm_only: bool = False  # No AscenAI login — enters via magic link
    can_access_admin: bool = False


class UpdateAgentSlotsRequest(BaseModel):
    quantity: int = Field(..., ge=1, le=100)


class UpdateCRMSeatsRequest(BaseModel):
    workspace_id: str
    seats: int = Field(..., ge=0, le=500)


class CreateWorkspaceRequest(BaseModel):
    company_name: str = Field(..., min_length=1, max_length=255)


# ─── Overview ──────────────────────────────────────────────────────────────────

@router.get("/overview")
async def get_overview(
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
):
    """Tenant Admin hub overview — products, seats, recent activity."""
    tenant_id_str, _, _ = _require_admin(request)
    tenant_uuid = uuid.UUID(tenant_id_str)

    tenant_res = await db.execute(select(Tenant).where(Tenant.id == tenant_uuid))
    tenant = tenant_res.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found.")

    usage_res = await db.execute(select(TenantUsage).where(TenantUsage.tenant_id == tenant_uuid))
    usage = usage_res.scalar_one_or_none()

    # Member counts
    member_total = await db.execute(
        select(func.count()).select_from(TenantMember).where(
            TenantMember.tenant_id == tenant_uuid,
            TenantMember.status == "active",
        )
    )
    crm_member_count = await db.execute(
        select(func.count()).select_from(TenantMember).where(
            TenantMember.tenant_id == tenant_uuid,
            TenantMember.can_access_crm.is_(True),
            TenantMember.status == "active",
        )
    )

    # CRM workspaces
    workspaces_res = await db.execute(
        select(TenantCRMWorkspace).where(
            TenantCRMWorkspace.tenant_id == tenant_uuid,
            TenantCRMWorkspace.is_active.is_(True),
        )
    )
    workspaces = workspaces_res.scalars().all()
    total_crm_slots = sum(w.user_slots for w in workspaces)

    return {
        "tenant": {
            "id": str(tenant.id),
            "name": tenant.name,
            "business_name": tenant.business_name,
            "plan": tenant.plan,
            "plan_display_name": tenant.plan_display_name,
            "subscription_status": tenant.subscription_status,
        },
        "products": {
            "agents": {
                "enabled": True,
                "agent_slots_purchased": usage.agent_count if usage else 0,
            },
            "crm": {
                "enabled": len(workspaces) > 0,
                "workspace_count": len(workspaces),
                "total_crm_seats": total_crm_slots,
                "crm_members_count": crm_member_count.scalar() or 0,
            },
        },
        "team": {
            "total_members": member_total.scalar() or 0,
        },
    }


# ─── Members & RBAC ────────────────────────────────────────────────────────────

@router.get("/members")
async def list_members(
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
    status: str = "active",
):
    """List all tenant members with their cross-product permissions."""
    tenant_id_str, _, _ = _require_admin(request)
    tenant_uuid = uuid.UUID(tenant_id_str)

    result = await db.execute(
        select(TenantMember)
        .where(
            TenantMember.tenant_id == tenant_uuid,
            TenantMember.status == status,
        )
        .order_by(TenantMember.created_at.asc())
    )
    members = result.scalars().all()

    return {
        "members": [
            {
                "id": str(m.id),
                "user_id": str(m.user_id) if m.user_id else None,
                "email": m.email,
                "full_name": m.full_name,
                "status": m.status,
                "is_crm_only": m.is_crm_only,
                "permissions": {
                    "can_access_agents": m.can_access_agents,
                    "can_access_crm": m.can_access_crm,
                    "can_access_billing": m.can_access_billing,
                    "can_access_admin": m.can_access_admin,
                    "agents_role": m.agents_role,
                    "crm_role": m.crm_role,
                },
                "crm_workspace_id": str(m.crm_workspace_id) if m.crm_workspace_id else None,
                "accepted_at": m.accepted_at.isoformat() if m.accepted_at else None,
                "created_at": m.created_at.isoformat(),
            }
            for m in members
        ],
        "total": len(members),
    }


@router.post("/members/invite", status_code=201)
async def invite_member(
    body: InviteMemberRequest,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
):
    """
    Invite a new member with cross-product permissions.
    CRM-only users are provisioned in Twenty and receive a magic link (no AscenAI account).
    """
    tenant_id_str, requestor_id, _ = _require_admin(request)
    tenant_uuid = uuid.UUID(tenant_id_str)

    # Check for existing member
    existing = await db.execute(
        select(TenantMember).where(
            TenantMember.tenant_id == tenant_uuid,
            TenantMember.email == body.email,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="A member with this email already exists.")

    # Generate invite token
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)

    crm_ws_id = uuid.UUID(body.crm_workspace_id) if body.crm_workspace_id else None

    member = TenantMember(
        tenant_id=tenant_uuid,
        email=body.email,
        full_name=body.full_name,
        can_access_agents=not body.is_crm_only,
        can_access_crm=body.can_access_crm or body.is_crm_only,
        can_access_billing=False,
        can_access_admin=body.can_access_admin,
        agents_role=body.agents_role,
        crm_role=body.crm_role,
        is_crm_only=body.is_crm_only,
        invite_token_hash=token_hash,
        invite_expires_at=expires_at,
        invited_by_user_id=uuid.UUID(requestor_id),
        status="pending",
        crm_workspace_id=crm_ws_id,
    )
    db.add(member)

    # For CRM-only users — also create the Twenty account immediately
    if body.is_crm_only and crm_ws_id:
        try:
            await crm_service.provision_user(
                mapping_id=crm_ws_id,
                email=body.email,
                full_name=body.full_name or body.email.split("@")[0],
            )
        except Exception as e:
            logger.warning("crm_user_provision_failed", email=body.email, error=str(e))

    await db.commit()
    await db.refresh(member)

    await audit_log(
        db=db, request=request,
        action="tenant_admin.member.invited",
        category="user",
        resource_type="tenant_member",
        resource_id=str(member.id),
        status="success",
        details={"email": body.email, "is_crm_only": body.is_crm_only},
    )

    # In production: send invite email with the raw_token link
    # For now, return the token for dev use
    return {
        "id": str(member.id),
        "email": member.email,
        "status": "pending",
        "invite_token": raw_token,  # Remove in production — email only
        "invite_expires_at": expires_at.isoformat(),
        "is_crm_only": body.is_crm_only,
    }


@router.patch("/members/{member_id}/permissions")
async def update_member_permissions(
    member_id: str,
    body: MemberPermissionsUpdate,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
):
    """Update cross-product permissions for a member."""
    tenant_id_str, requestor_id, _ = _require_admin(request)
    tenant_uuid = uuid.UUID(tenant_id_str)

    result = await db.execute(
        select(TenantMember).where(
            TenantMember.id == uuid.UUID(member_id),
            TenantMember.tenant_id == tenant_uuid,
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found.")

    updates: dict = body.model_dump(exclude_none=True)
    if "crm_workspace_id" in updates:
        updates["crm_workspace_id"] = uuid.UUID(updates["crm_workspace_id"]) if updates["crm_workspace_id"] else None
    for field, value in updates.items():
        setattr(member, field, value)

    await db.commit()
    await audit_log(
        db=db, request=request,
        action="tenant_admin.member.permissions_updated",
        category="user",
        resource_type="tenant_member",
        resource_id=member_id,
        status="success",
        details=updates,
    )
    return {"id": member_id, "updated": True}


@router.delete("/members/{member_id}", status_code=204)
async def revoke_member(
    member_id: str,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
):
    """Revoke a member's access across all products."""
    tenant_id_str, requestor_id, _ = _require_admin(request)
    tenant_uuid = uuid.UUID(tenant_id_str)

    result = await db.execute(
        select(TenantMember).where(
            TenantMember.id == uuid.UUID(member_id),
            TenantMember.tenant_id == tenant_uuid,
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found.")
    if str(member.user_id) == requestor_id:
        raise HTTPException(status_code=400, detail="Cannot revoke your own access.")

    member.status = "revoked"
    await db.commit()
    await audit_log(
        db=db, request=request,
        action="tenant_admin.member.revoked",
        category="user",
        resource_type="tenant_member",
        resource_id=member_id,
        status="success",
    )


# ─── Billing — Agent Slots ─────────────────────────────────────────────────────

@router.get("/billing/overview")
async def billing_overview(
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
):
    """Unified billing overview for Admin Portal."""
    tenant_id_str, _, _ = _require_admin(request)
    tenant_uuid = uuid.UUID(tenant_id_str)

    tenant_res = await db.execute(select(Tenant).where(Tenant.id == tenant_uuid))
    tenant = tenant_res.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found.")

    usage_res = await db.execute(select(TenantUsage).where(TenantUsage.tenant_id == tenant_uuid))
    usage = usage_res.scalar_one_or_none()

    workspaces_res = await db.execute(
        select(TenantCRMWorkspace).where(
            TenantCRMWorkspace.tenant_id == tenant_uuid,
            TenantCRMWorkspace.is_active.is_(True),
        )
    )
    workspaces = workspaces_res.scalars().all()
    total_crm_seats = sum(w.user_slots for w in workspaces)

    from app.api.v1.billing import DEFAULT_PLANS
    plan_data = DEFAULT_PLANS.get(tenant.plan or "growth", DEFAULT_PLANS.get("growth", {}))

    agent_count = usage.agent_count if usage else 0
    agent_cost = agent_count * (plan_data.get("price_per_agent") or settings.AGENT_SLOT_PRICE_FALLBACK)
    crm_cost = total_crm_seats * settings.CRM_SEAT_PRICE

    return {
        "plan": tenant.plan,
        "plan_display_name": tenant.plan_display_name,
        "subscription_status": tenant.subscription_status,
        "agent_slots": {
            "purchased": agent_count,
            "price_per_slot": plan_data.get("price_per_agent") or settings.AGENT_SLOT_PRICE_FALLBACK,
            "monthly_cost": round(agent_cost, 2),
        },
        "crm_seats": {
            "total_purchased": total_crm_seats,
            "price_per_seat": settings.CRM_SEAT_PRICE,
            "monthly_cost": round(crm_cost, 2),
        },
        "estimated_total": round(agent_cost + crm_cost, 2),
        "stripe_customer_id": tenant.stripe_customer_id,
        "subscription_id": tenant.subscription_id,
    }



@router.post("/billing/agent-slots/update")
async def update_agent_slots(
    body: UpdateAgentSlotsRequest,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
):
    """
    Update agent slot quantity via Stripe subscription modification.
    Handles both increase and decrease with automatic proration.
    """
    import asyncio
    import stripe as _stripe
    tenant_id_str, _, _ = _require_admin(request)
    tenant_uuid = uuid.UUID(tenant_id_str)

    tenant_res = await db.execute(select(Tenant).where(Tenant.id == tenant_uuid))
    tenant = tenant_res.scalar_one_or_none()
    if not tenant or not tenant.subscription_id:
        raise HTTPException(status_code=400, detail="No active subscription found.")

    _stripe.api_key = settings.STRIPE_SECRET_KEY
    try:
        subscription = await asyncio.to_thread(_stripe.Subscription.retrieve, tenant.subscription_id)
        # Find the agent slot line item (first item in subscription)
        items = subscription.get("items", {}).get("data", [])
        if not items:
            raise HTTPException(status_code=400, detail="Subscription has no line items.")

        agent_item = next(
            (item for item in items if "agent" in (item.get("price", {}).get("nickname") or "").lower()),
            items[0]  # Fallback to first item
        )

        updated_sub = await asyncio.to_thread(
            _stripe.SubscriptionItem.modify,
            agent_item["id"],
            quantity=body.quantity,
            proration_behavior="create_prorations",
        )

        # Sync to DB
        usage_res = await db.execute(select(TenantUsage).where(TenantUsage.tenant_id == tenant_uuid))
        usage = usage_res.scalar_one_or_none()
        if usage:
            usage.agent_count = body.quantity
            await db.commit()

        await audit_log(
            db=db, request=request,
            action="tenant_admin.billing.agent_slots_updated",
            category="billing",
            resource_type="subscription",
            resource_id=tenant.subscription_id,
            status="success",
            details={"new_quantity": body.quantity},
        )
        return {"success": True, "quantity": body.quantity, "proration_applied": True}
    except _stripe.error.StripeError as e:
        logger.error("agent_slots_stripe_error", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to update Stripe subscription.")


@router.post("/billing/crm-seats/update")
async def update_crm_seats(
    body: UpdateCRMSeatsRequest,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
):
    """Update CRM seat quantity for a specific workspace."""
    tenant_id_str, _, _ = _require_admin(request)
    tenant_uuid = uuid.UUID(tenant_id_str)

    ws_res = await db.execute(
        select(TenantCRMWorkspace).where(
            TenantCRMWorkspace.id == uuid.UUID(body.workspace_id),
            TenantCRMWorkspace.tenant_id == tenant_uuid,
        )
    )
    workspace = ws_res.scalar_one_or_none()
    if not workspace:
        raise HTTPException(status_code=404, detail="CRM workspace not found.")

    workspace.user_slots = body.seats
    await db.commit()

    await audit_log(
        db=db, request=request,
        action="tenant_admin.billing.crm_seats_updated",
        category="billing",
        resource_type="crm_workspace",
        resource_id=body.workspace_id,
        status="success",
        details={"new_seats": body.seats},
    )
    return {"success": True, "workspace_id": body.workspace_id, "seats": body.seats}


# ─── CRM Workspace Management ─────────────────────────────────────────────────

@router.get("/crm/workspaces")
async def list_crm_workspaces(
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
):
    """List all CRM workspaces for the tenant."""
    tenant_id_str, _, _ = _require_admin(request)
    tenant_uuid = uuid.UUID(tenant_id_str)

    result = await db.execute(
        select(TenantCRMWorkspace).where(
            TenantCRMWorkspace.tenant_id == tenant_uuid,
            TenantCRMWorkspace.is_active.is_(True),
        ).order_by(TenantCRMWorkspace.created_at.asc())
    )
    workspaces = result.scalars().all()

    return {
        "workspaces": [
            {
                "id": str(w.id),
                "company_name": w.company_name,
                "subdomain": w.subdomain,
                "user_slots": w.user_slots,
                "url": f"http://{w.subdomain}.{settings.ROOT_DOMAIN}:{settings.CRM_PORT}",
                "created_at": w.created_at.isoformat(),
            }
            for w in workspaces
        ]
    }


@router.post("/crm/workspaces", status_code=201)
async def create_crm_workspace(
    body: CreateWorkspaceRequest,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
):
    """Create a new CRM workspace (Company) for this tenant."""
    tenant_id_str, user_id, _ = _require_admin(request)
    tenant_uuid = uuid.UUID(tenant_id_str)

    tenant_res = await db.execute(select(Tenant).where(Tenant.id == tenant_uuid))
    tenant = tenant_res.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found.")

    user_res = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    owner = user_res.scalar_one_or_none()

    try:
        result = await crm_service.create_crm_workspace(
            tenant_id=tenant_uuid,
            company_name=body.company_name,
            owner_email=owner.email if owner else tenant.email,
            owner_full_name=owner.full_name if owner else "Admin",
        )
    except Exception as e:
        logger.error("crm_workspace_create_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to create CRM workspace.")

    await audit_log(
        db=db, request=request,
        action="tenant_admin.crm.workspace_created",
        category="tenant",
        resource_type="crm_workspace",
        resource_id=result["workspace_id"],
        status="success",
        details={"company_name": body.company_name},
    )
    return result


@router.get("/crm/sso-link")
async def get_crm_sso_link(
    request: Request,
    workspace_id: Optional[str] = None,
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
):
    """Generate a one-click SSO link to enter the CRM as the current user."""
    _, user_id, _ = _require_admin(request)

    user_res = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = user_res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    try:
        session_id = await crm_service.generate_sso_session(email=user.email)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="Your account is not yet provisioned in the CRM. Please ensure the CRM add-on is active."
        )

    # Determine target subdomain
    target_subdomain = "app"
    if workspace_id:
        ws_res = await db.execute(
            select(TenantCRMWorkspace).where(TenantCRMWorkspace.id == uuid.UUID(workspace_id))
        )
        ws = ws_res.scalar_one_or_none()
        if ws:
            target_subdomain = ws.subdomain

    crm_base = f"http://{target_subdomain}.{settings.ROOT_DOMAIN}:{settings.CRM_PORT}"
    return {
        "session_id": session_id,
        "crm_url": crm_base,
        "cookie": {
            "name": "connect.sid",
            "value": f"s:{session_id}",
            "domain": settings.COOKIE_DOMAIN or f".{settings.ROOT_DOMAIN}",
            "path": "/",
            "http_only": True,
        },
    }


# ─── Org Settings ──────────────────────────────────────────────────────────────

@router.get("/settings")
async def get_org_settings(
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
):
    """Get organization settings."""
    tenant_id_str, _, _ = _require_admin(request)
    tenant_uuid = uuid.UUID(tenant_id_str)

    tenant_res = await db.execute(select(Tenant).where(Tenant.id == tenant_uuid))
    tenant = tenant_res.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found.")

    return {
        "id": str(tenant.id),
        "name": tenant.name,
        "business_name": tenant.business_name,
        "business_type": tenant.business_type,
        "email": tenant.email,
        "phone": tenant.phone,
        "address": tenant.address,
        "timezone": tenant.timezone,
        "slug": tenant.slug,
    }


class OrgSettingsUpdate(BaseModel):
    business_name: Optional[str] = Field(None, max_length=255)
    business_type: Optional[str] = Field(None, max_length=100)
    phone: Optional[str] = Field(None, max_length=50)
    address: Optional[dict] = None
    timezone: Optional[str] = Field(None, max_length=100)


@router.patch("/settings")
async def update_org_settings(
    body: OrgSettingsUpdate,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
):
    """Update organization settings."""
    tenant_id_str, _, _ = _require_admin(request)
    tenant_uuid = uuid.UUID(tenant_id_str)

    tenant_res = await db.execute(select(Tenant).where(Tenant.id == tenant_uuid))
    tenant = tenant_res.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found.")

    updates = body.model_dump(exclude_none=True)
    for field, value in updates.items():
        setattr(tenant, field, value)

    await db.commit()
    await audit_log(
        db=db, request=request,
        action="tenant_admin.settings.updated",
        category="tenant",
        resource_type="tenant",
        resource_id=str(tenant.id),
        status="success",
        details=updates,
    )
    return {"success": True}
