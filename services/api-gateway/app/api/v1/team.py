from __future__ import annotations

import secrets
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_scope
from app.models.user import User
from app.services.auth_service import auth_service

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
    db: AsyncSession = Depends(get_db),
    page: int = 1,
    limit: int = 50,
):
    """List users in the tenant. Requires owner or admin role. Paginated."""
    tenant_id, _ = _require_management(request)

    if page < 1:
        page = 1
    limit = min(max(limit, 1), 200)  # clamp 1–200
    offset = (page - 1) * limit

    result = await db.execute(
        select(User)
        .where(User.tenant_id == uuid.UUID(tenant_id))
        .order_by(User.created_at.asc())
        .limit(limit)
        .offset(offset)
    )
    return [_user_to_response(u) for u in result.scalars().all()]


@router.post("/invite", response_model=TeamMemberResponse, status_code=201)
async def invite_user(
    body: InviteRequest,
    request: Request,
    _scope=require_scope("team:write"),
    db: AsyncSession = Depends(get_db),
):
    """
    Invite a new user to the tenant.
    Creates a user with a random temporary password.
    In production an invitation email would be sent.
    """
    tenant_id, _ = _require_management(request)

    if body.role not in _VALID_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role '{body.role}'. Valid roles: {', '.join(sorted(_VALID_ROLES))}",
        )

    # Normalize email to lowercase before any comparison or storage
    normalized_email = body.email.lower()

    # Check uniqueness WITHIN THIS TENANT ONLY (prevents cross-tenant enumeration)
    existing = await db.execute(
        select(User).where(
            User.email == normalized_email,
            User.tenant_id == uuid.UUID(tenant_id),
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="A user with this email already exists.")

    # Generate a random 12-character temp password
    temp_password = secrets.token_urlsafe(9)  # ~12 chars

    new_user = User(
        id=uuid.uuid4(),
        tenant_id=uuid.UUID(tenant_id),
        email=normalized_email,
        hashed_password=auth_service.hash_password(temp_password),
        full_name=body.full_name,
        role=body.role,
        is_active=True,
        is_email_verified=False,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    # In a real system, send an invite email with the temp password / magic link
    logger.info(
        "user_invited",
        invited_email=body.email,
        role=body.role,
        tenant_id=tenant_id,
        # temp_password is intentionally NOT logged in production
    )

    return _user_to_response(new_user)


@router.patch("/{user_id}/role", response_model=TeamMemberResponse)
async def change_user_role(
    user_id: str,
    body: RoleChangeRequest,
    request: Request,
    _scope=require_scope("team:write"),
    db: AsyncSession = Depends(get_db),
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
        owner_count_result = await db.execute(
            select(func.count()).select_from(User).where(
                User.tenant_id == uuid.UUID(tenant_id),
                User.role == "owner",
                User.is_active.is_(True),
            )
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
    db: AsyncSession = Depends(get_db),
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
        owner_count_result = await db.execute(
            select(func.count()).select_from(User).where(
                User.tenant_id == uuid.UUID(tenant_id),
                User.role == "owner",
                User.is_active.is_(True),
            )
        )
        owner_count = owner_count_result.scalar() or 0
        if owner_count <= 1:
            raise HTTPException(
                status_code=400,
                detail="Cannot remove the last owner. Assign another owner first.",
            )

    target.is_active = False
    await db.commit()
    logger.info("user_deactivated", user_id=user_id, tenant_id=tenant_id)
