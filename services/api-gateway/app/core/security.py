from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator, Optional
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
import structlog
import uuid

from app.core.config import settings

logger = structlog.get_logger(__name__)

security = HTTPBearer(auto_error=False)

# Hardened JWT options — reject tokens missing issuer / audience claims
# when the settings values are configured (non-empty).
_JWT_OPTIONS = {
    "verify_exp": True,
    "verify_iss": bool(getattr(settings, "JWT_ISSUER", "")),
    "verify_aud": bool(getattr(settings, "JWT_AUDIENCE", "")),
}


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    )
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Decode and validate a JWT access token.

    Enforces:
    - Signature and expiry (always)
    - Token type must be None or 'access' (refresh tokens rejected)
    - Issuer / audience when configured via settings.JWT_ISSUER / JWT_AUDIENCE
    - Tenant ID must be a valid UUID
    """
    try:
        decode_kwargs: dict = {
            "algorithms": [settings.JWT_ALGORITHM],
            "options": _JWT_OPTIONS,
        }
        issuer = getattr(settings, "JWT_ISSUER", "")
        audience = getattr(settings, "JWT_AUDIENCE", "")
        if issuer:
            decode_kwargs["issuer"] = issuer
        if audience:
            decode_kwargs["audience"] = audience

        payload = jwt.decode(token, settings.SECRET_KEY, **decode_kwargs)

        if payload.get("type") not in (None, "access"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Enforce tenant_id is a well-formed UUID to prevent injection
        tenant_id = payload.get("tenant_id", "")
        try:
            uuid.UUID(str(tenant_id))
        except (ValueError, AttributeError):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Malformed token claims",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return payload
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


async def get_current_tenant(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> str:
    """
    Extract tenant_id from a valid JWT Bearer token or HttpOnly cookie.

    SECURITY: The unauthenticated X-Tenant-ID header fallback has been removed.
    A valid, signed JWT is now mandatory for all protected endpoints.
    The X-Tenant-ID header is only accepted from trusted internal services
    that pass through the AuthMiddleware (which sets request.state.tenant_id).
    """
    # 1. Try Authorization: Bearer <token> or cookie-based token
    if credentials:
        payload = decode_access_token(credentials.credentials)
        tenant_id = payload.get("tenant_id")
        if tenant_id:
            return str(tenant_id)

    # 2. Internal service path: AuthMiddleware already validated the request
    #    and stamped request.state.tenant_id. Accept only that — NOT the raw header.
    state_tenant = getattr(request.state, "tenant_id", None)
    if state_tenant:
        return str(state_tenant)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_optional_tenant(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[str]:
    """Extract optional tenant_id from a valid JWT or already-authenticated request state."""
    if credentials:
        try:
            payload = decode_access_token(credentials.credentials)
            return payload.get("tenant_id")
        except HTTPException:
            pass
    return getattr(request.state, "tenant_id", None)


async def get_tenant_db(
    tenant_id: str = Depends(get_current_tenant),
) -> AsyncGenerator[AsyncSession, None]:
    """Composed dependency: authenticates the request AND yields a tenant-scoped DB session.

    The session has ``SET LOCAL app.current_tenant_id = <tenant_id>`` already
    applied, so all Postgres RLS policies are automatically enforced.
    """
    from app.core.database import get_db
    async for session in get_db(tenant_id=tenant_id):
        yield session
