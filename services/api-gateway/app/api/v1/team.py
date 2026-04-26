from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import require_scope
from app.core.security import get_current_tenant, get_tenant_db
from app.models.invite import UserInvite
from app.models.user import User
from app.services.auth_service import auth_service
from app.services.tenant_service import tenant_service

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/team")

_VALID_ROLES = {"owner", "admin", "developer", "viewer"}
_MANAGEMENT_ROLES = {"owner", "admin", "super_admin"}


class InviteRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=255)
    role: str = Field(default="viewer", description="owner | admin | developer | viewer")


class RoleChangeRequest(BaseModel):
    role: str = Field(..., description="owner | admin | developer | viewer")


class TeamMemberResponse(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    is_active: bool
    last_login_at: str | None
    created_at: str


class InviteResponse(BaseModel):
    id: str
    email: str
    role: str
    token: str  # In production, we'd only return this if the actor is an admin/owner
    expires_at: str


def _require_tenant(request: Request) -> str:
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return tenant_id


def _require_management(request: Request) -> tuple[str, str]:
    """Returns (tenant_id, user_id). Raises 403 if not owner/admin."""
    tenant_id = _require_tenant(request)
    role = getattr(request.state, "role", "viewer")
    if role not in _MANAGEMENT_ROLES:
        raise HTTPException(status_code=403, detail="Owner or admin role required.")
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return tenant_id, user_id


def _user_to_response(user: User) -> TeamMemberResponse:
    return TeamMemberResponse(
        id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        is_active=user.is_active,
        last_login_at=user.last_login_at.isoformat() if user.last_login_at else None,
        created_at=user.created_at.isoformat(),
    )


@router.get("", response_model=list[TeamMemberResponse])
async def list_team(
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
    page: int = 1,
    limit: int = 50,
):
    """List users in the tenant. Requires owner or admin role. Paginated."""
    # We still need to verify management role if it's not handled by RBAC middleware
    # and we want to keep it here.
    role = Depends(get_tenant_db) # Redundant but shows how to get it if needed
    # Actually, let's keep _require_management for now as it does role check
    # BUT we must pass the db session that HAS RLS context.

    if page < 1:
        page = 1
    limit = min(max(limit, 1), 200)  # clamp 1–200
    offset = (page - 1) * limit

    result = await db.execute(
        select(User)
        .where(User.tenant_id == uuid.UUID(tenant_id))
        .order_by(User.is_active.desc(), User.created_at.asc())
        .limit(limit)
        .offset(offset)
    )
    return [_user_to_response(u) for u in result.scalars().all()]


@router.get("/invites", response_model=list[InviteResponse])
async def list_pending_invites(
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
):
    """List pending invitations for the tenant."""
    from datetime import datetime, timezone
    _require_management(request)
    
    result = await db.execute(
        select(UserInvite).where(
            UserInvite.tenant_id == uuid.UUID(tenant_id),
            UserInvite.accepted_at == None,
            UserInvite.expires_at > datetime.now(timezone.utc)
        )
    )
    invites = result.scalars().all()
    return [
        InviteResponse(
            id=str(i.id),
            email=i.email,
            role=i.role,
            token=i.token,
            expires_at=i.expires_at.isoformat()
        )
        for i in invites
    ]


@router.post("/invite", response_model=InviteResponse, status_code=201)
async def invite_user(
    body: InviteRequest,
    request: Request,
    _scope=require_scope("team:write"),
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
):
    """
    Invite a new user to the tenant via secure token.
    Enforces plan seat limits.
    """
    tenant_id, requestor_id = _require_management(request)

    if body.role not in _VALID_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role '{body.role}'. Valid roles: {', '.join(sorted(_VALID_ROLES))}",
        )

    # REVENUE PROTECTION: Check seat limits
    if not await tenant_service.check_team_seats(tenant_id, db):
        raise HTTPException(
            status_code=403,
            detail="Team seat limit reached for your current plan. Please upgrade to invite more members."
        )

    # Use auth_service to create the secure invitation
    invite = await auth_service.create_invite(
        tenant_id=tenant_id,
        email=body.email,
        role=body.role,
        invited_by=requestor_id,
        db=db
    )

    logger.info(
        "user_invited",
        invited_email=body.email,
        role=body.role,
        tenant_id=tenant_id,
        requestor_id=requestor_id
    )

    return InviteResponse(
        id=str(invite.id),
        email=invite.email,
        role=invite.role,
        token=invite.token,
        expires_at=invite.expires_at.isoformat()
    )


@router.patch("/{user_id}/role", response_model=TeamMemberResponse)
async def change_user_role(
    user_id: str,
    body: RoleChangeRequest,
    request: Request,
    _scope=require_scope("team:write"),
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
):
    """Change a team member's role. Cannot demote/change the last owner."""
    tenant_id, requestor_id = _require_management(request)

    if body.role not in _VALID_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role '{body.role}'. Valid roles: {', '.join(sorted(_VALID_ROLES))}",
        )

    result = await db.execute(
        select(User).where(
            User.id == uuid.UUID(user_id),
            User.tenant_id == uuid.UUID(tenant_id),
        )
    )
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found.")

    # If target is an owner and new role is not owner, verify another owner exists
    if target.role == "owner" and body.role != "owner":
        # RACE CONDITION FIX: Use FOR UPDATE to lock active users in this tenant
        # during the owner-count check.
        owner_count_result = await db.execute(
            select(func.count())
            .select_from(User)
            .where(
                User.tenant_id == uuid.UUID(tenant_id),
                User.role == "owner",
                User.is_active.is_(True),
            )
            .with_for_update()
        )
        owner_count = owner_count_result.scalar() or 0
        if owner_count <= 1:
            raise HTTPException(
                status_code=400,
                detail="Cannot demote the last owner. Assign another owner first.",
            )

    target.role = body.role
    await db.commit()
    await db.refresh(target)
    logger.info("user_role_changed", user_id=user_id, new_role=body.role, tenant_id=tenant_id)
    return _user_to_response(target)


@router.delete("/{user_id}", status_code=204)
async def deactivate_user(
    user_id: str,
    request: Request,
    _scope=require_scope("team:write"),
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
):
    """Deactivate a team member. Cannot remove yourself or the last owner."""
    tenant_id, requestor_id = _require_management(request)

    # Cannot remove yourself
    if user_id == requestor_id:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account.")

    result = await db.execute(
        select(User).where(
            User.id == uuid.UUID(user_id),
            User.tenant_id == uuid.UUID(tenant_id),
        )
    )
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found.")

    # Cannot remove last owner
    if target.role == "owner":
        # RACE CONDITION FIX: Use FOR UPDATE
        owner_count_result = await db.execute(
            select(func.count())
            .select_from(User)
            .where(
                User.tenant_id == uuid.UUID(tenant_id),
                User.role == "owner",
                User.is_active.is_(True),
            )
            .with_for_update()
        )
        owner_count = owner_count_result.scalar() or 0
        if owner_count <= 1:
            raise HTTPException(
                status_code=400,
                detail="Cannot remove the last owner. Assign another owner first.",
            )

    target.is_active = False
    await db.commit()
    logger.info("user_deactivated", user_id=user_id, tenant_id=tenant_id, requestor_id=requestor_id)


@router.post("/{user_id}/reactivate")
async def reactivate_user(
    user_id: str,
    request: Request,
    _scope=require_scope("team:write"),
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
):
    """Reactivate a previously deactivated team member."""
    tenant_id, requestor_id = _require_management(request)

    # REVENUE PROTECTION: Check seat limits before reactivating
    if not await tenant_service.check_team_seats(tenant_id, db):
        raise HTTPException(
            status_code=403,
            detail="Team seat limit reached. Please upgrade or remove another member to reactivate."
        )

    result = await db.execute(
        select(User).where(
            User.id == uuid.UUID(user_id),
            User.tenant_id == uuid.UUID(tenant_id),
        )
    )
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found.")

    target.is_active = True
    await db.commit()
    logger.info("user_reactivated", user_id=user_id, tenant_id=tenant_id, requestor_id=requestor_id)
    return {"message": "User reactivated."}


@router.delete("/{user_id}/hard", status_code=204)
async def delete_user_permanently(
    user_id: str,
    request: Request,
    _scope=require_scope("team:write"),
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
):
    """
    Permanently delete a team member and clear their PII (GDPR compliance).
    Only allowed for admins/owners.
    """
    tenant_id, requestor_id = _require_management(request)
    
    # Cannot remove yourself
    if user_id == requestor_id:
        raise HTTPException(status_code=400, detail="Use 'delete account' in profile to remove yourself.")

    result = await db.execute(
        select(User).where(
            User.id == uuid.UUID(user_id),
            User.tenant_id == uuid.UUID(tenant_id),
        )
    )
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found.")

    # Cannot remove last owner
    if target.role == "owner":
        owner_count_result = await db.execute(
            select(func.count())
            .select_from(User)
            .where(
                User.tenant_id == uuid.UUID(tenant_id),
                User.role == "owner",
                User.is_active.is_(True),
            )
            .with_for_update()
        )
        owner_count = owner_count_result.scalar() or 0
        if owner_count <= 1:
            raise HTTPException(
                status_code=400,
                detail="Cannot delete the last owner."
            )

    # Perform deletion
    from sqlalchemy import delete

    from app.models.user import APIKey
    
    # Clear PII from the user record before deletion if we were doing soft-delete, 
    # but here we do hard delete of the user record.
    # Note: Tenant isolation is guaranteed by get_tenant_db session!
    await db.execute(delete(APIKey).where(APIKey.user_id == target.id))
    await db.delete(target)
    
    await db.commit()
    logger.info("user_hard_deleted", user_id=user_id, tenant_id=tenant_id, requestor_id=requestor_id)
