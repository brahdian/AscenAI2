from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_tenant, get_current_user, get_tenant_db
from app.models.user import APIKey
from app.schemas.auth import (
    APIKeyCreatedResponse,
    APIKeyCreateRequest,
    APIKeyResponse,
    APIKeyUpdateRequest,
)
from app.services.auth_service import auth_service

router = APIRouter(prefix="/api-keys")

# Scopes available to any authenticated user
_USER_SCOPES = frozenset({"chat", "sessions", "feedback"})
# Scopes that require owner or admin role
_PRIVILEGED_SCOPES = frozenset({"admin", "agents:write", "api-keys:write", "tenants:write"})
# All valid scopes
_ALL_VALID_SCOPES = _USER_SCOPES | _PRIVILEGED_SCOPES | frozenset({"agents:read", "analytics"})


def _require_tenant(request: Request) -> str:
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return tenant_id


@router.post("", response_model=APIKeyCreatedResponse, status_code=201)
async def create_api_key(
    body: APIKeyCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
    user_id: str = Depends(get_current_user),
):
    """Create a new API key. The raw key is shown only once."""
    # Auth is handled by get_tenant_db dependency

    # Check plan limit: max_api_keys
    from app.models.tenant import Tenant
    from app.services.tenant_service import check_limit, get_plan_limits
    t_res = await db.execute(select(Tenant).where(Tenant.id == uuid.UUID(tenant_id)))
    tenant = t_res.scalar_one_or_none()
    limits = await get_plan_limits(tenant.plan if tenant else "professional", db)
    existing_count_res = await db.execute(
        select(APIKey).where(APIKey.tenant_id == uuid.UUID(tenant_id), APIKey.is_active.is_(True))
    )
    existing_count = len(existing_count_res.scalars().all())
    if not check_limit(limits["max_api_keys"], existing_count):
        raise HTTPException(
            status_code=429,
            detail=f"API key limit reached: your plan allows up to {limits['max_api_keys']} active key(s). "
                   f"Delete an existing key or upgrade your plan.",
        )

    # Validate requested scopes
    requested = set(body.scopes)
    invalid = requested - _ALL_VALID_SCOPES
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid scope(s): {', '.join(sorted(invalid))}. "
                   f"Valid scopes: {', '.join(sorted(_ALL_VALID_SCOPES))}",
        )

    # Only owner/admin users may request privileged scopes
    user_role = getattr(request.state, "role", "member")
    if requested & _PRIVILEGED_SCOPES and user_role not in {"owner", "admin"}:
        raise HTTPException(
            status_code=403,
            detail="Only owner or admin users may request privileged scopes.",
        )

    expires_at: datetime | None = None
    if body.expires_at:
        try:
            expires_at = datetime.fromisoformat(body.expires_at).replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid expires_at format. Use ISO 8601.")
    
    # Enforce maximum 90 day expiration (Zenith Pillar)
    max_expiry = datetime.now(timezone.utc) + timedelta(days=90)
    if not expires_at or expires_at > max_expiry:
        expires_at = max_expiry

    raw_key, api_key = await auth_service.create_api_key(
        tenant_id=uuid.UUID(tenant_id),
        user_id=uuid.UUID(user_id),
        name=body.name,
        scopes=body.scopes,
        db=db,
        expires_at=expires_at,
        agent_id=uuid.UUID(body.agent_id) if body.agent_id else None,
        allowed_origins=body.allowed_origins,
    )
    return APIKeyCreatedResponse(
        id=str(api_key.id),
        name=api_key.name,
        key_prefix=api_key.key_prefix,
        scopes=api_key.scopes,
        rate_limit_per_minute=api_key.rate_limit_per_minute,
        is_active=api_key.is_active,
        last_used_at=api_key.last_used_at.isoformat() if api_key.last_used_at else None,
        expires_at=api_key.expires_at.isoformat() if api_key.expires_at else None,
        created_at=api_key.created_at.isoformat(),
        raw_key=raw_key,
    )


@router.get("", response_model=list[APIKeyResponse])
async def list_api_keys(
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
    page: int = 1,
    limit: int = 50,
):
    """List all API keys for the current tenant. Paginated."""
    if page < 1:
        page = 1
    limit = min(max(limit, 1), 200)
    offset = (page - 1) * limit
    result = await db.execute(
        select(APIKey)
        .where(
            APIKey.tenant_id == uuid.UUID(tenant_id),
            APIKey.is_active.is_(True),
        )
        .order_by(APIKey.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    keys = result.scalars().all()
    return [
        APIKeyResponse(
            id=str(k.id),
            name=k.name,
            key_prefix=k.key_prefix,
            scopes=k.scopes,
            rate_limit_per_minute=k.rate_limit_per_minute,
            is_active=k.is_active,
            last_used_at=k.last_used_at.isoformat() if k.last_used_at else None,
            expires_at=k.expires_at.isoformat() if k.expires_at else None,
            created_at=k.created_at.isoformat(),
            agent_id=str(k.agent_id) if k.agent_id else None,
            allowed_origins=k.allowed_origins,
        )
        for k in keys
    ]


@router.patch("/{key_id}", response_model=APIKeyResponse)
async def update_api_key(
    key_id: str,
    body: APIKeyUpdateRequest,
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
):
    """Update API key metadata (name, origins)."""
    result = await db.execute(
        select(APIKey).where(
            APIKey.id == uuid.UUID(key_id),
            APIKey.tenant_id == uuid.UUID(tenant_id),
        )
    )
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found.")

    if body.name is not None:
        api_key.name = body.name
    if body.allowed_origins is not None:
        api_key.allowed_origins = body.allowed_origins
    if body.is_active is not None:
        api_key.is_active = body.is_active

    await db.commit()
    await db.refresh(api_key)
    return [
        APIKeyResponse(
            id=str(api_key.id),
            name=api_key.name,
            key_prefix=api_key.key_prefix,
            scopes=api_key.scopes,
            rate_limit_per_minute=api_key.rate_limit_per_minute,
            is_active=api_key.is_active,
            last_used_at=api_key.last_used_at.isoformat() if api_key.last_used_at else None,
            expires_at=api_key.expires_at.isoformat() if api_key.expires_at else None,
            created_at=api_key.created_at.isoformat(),
            agent_id=str(api_key.agent_id) if api_key.agent_id else None,
            allowed_origins=api_key.allowed_origins,
        )
    ][0]


@router.delete("/{key_id}", status_code=204)
async def revoke_api_key(
    key_id: str,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
):

    """Revoke (soft-delete) an API key."""
    result = await db.execute(
        select(APIKey).where(
            APIKey.id == uuid.UUID(key_id),
            APIKey.tenant_id == uuid.UUID(tenant_id),
        )
    )
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found.")
    api_key.is_active = False
    await db.commit()

    # Instant Revocation: Wipe the Redis cache so the key is rejected immediately (Phase 10)
    redis = getattr(request.app.state, "redis", None)
    await auth_service.invalidate_api_key_cache(api_key.key_hash, redis=redis)

    from app.services.audit_service import audit_log
    await audit_log(
        db=db,
        action="api_key.revoked",
        tenant_id=tenant_id,
        category="security",
        resource_type="api_key",
        resource_id=str(api_key.id),
        status="success",
        details={"name": api_key.name, "key_prefix": api_key.key_prefix},
    )
