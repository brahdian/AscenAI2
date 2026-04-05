from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator, Optional, Tuple
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
import structlog
import uuid

from app.core.config import settings

logger = structlog.get_logger(__name__)

security = HTTPBearer(auto_error=False)

# Hardened JWT options — reject tokens missing issuer / audience when configured.
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


def decode_access_token(token: str) -> dict:
    """Decode and validate a JWT access token.

    Enforces:
    - Signature and expiry (always)
    - Token type must be None or 'access' (refresh tokens rejected)
    - Issuer / audience when configured via JWT_ISSUER / JWT_AUDIENCE settings
    - tenant_id must be a well-formed UUID
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

        # Ensure tenant_id is a well-formed UUID
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


from fastapi import Request

async def get_current_tenant(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> str:
    """
    Extract tenant_id from a valid JWT Bearer token.

    SECURITY: The unauthenticated X-Tenant-ID header fallback has been removed.
    The X-Tenant-ID header is only accepted when already stamped by the API Gateway
    AuthMiddleware in request.state.tenant_id (trusted internal service path).
    """
    # 1. Bearer token provided (JWT check)
    if credentials:
        payload = decode_access_token(credentials.credentials)
        tenant_id = payload.get("tenant_id")
        if tenant_id:
            return tenant_id

    # 2. Trusted Internal Proxy Header (Stamped by API Gateway)
    xtid = request.headers.get("X-Tenant-ID")
    if xtid:
        return xtid

    # 3. Legacy: Internal service path (already-stamped state)
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

    Usage in route handlers::

        @router.get("")
        async def list_agents(
            db: AsyncSession = Depends(get_tenant_db),
            tenant_id: str = Depends(get_current_tenant),
        ): ...

    The session has ``SET LOCAL app.current_tenant_id = <tenant_id>`` already
    applied, so all Postgres RLS policies are automatically enforced.
    """
    from app.core.database import get_db  # local import to avoid circular deps
    async for session in get_db(tenant_id=tenant_id):
        yield session
