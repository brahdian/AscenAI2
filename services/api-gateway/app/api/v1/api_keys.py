from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import APIKey
from app.schemas.auth import APIKeyCreateRequest, APIKeyCreatedResponse, APIKeyResponse
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
    db: AsyncSession = Depends(get_db),
):
    """Create a new API key. The raw key is shown only once."""
    tenant_id = _require_tenant(request)
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required.")

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

    raw_key, api_key = await auth_service.create_api_key(
        tenant_id=uuid.UUID(tenant_id),
        user_id=uuid.UUID(user_id),
        name=body.name,
        scopes=body.scopes,
        db=db,
        expires_at=expires_at,
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
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = 1,
    limit: int = 50,
):
    """List all API keys for the current tenant. Paginated."""
    tenant_id = _require_tenant(request)
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
        )
        for k in keys
    ]


@router.delete("/{key_id}", status_code=204)
async def revoke_api_key(
    key_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Revoke (soft-delete) an API key."""
    tenant_id = _require_tenant(request)
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
