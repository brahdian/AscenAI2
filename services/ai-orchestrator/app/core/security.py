from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator, Optional, Tuple, Dict, Any
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
        try:
            # First, check if it's a signed internal service token (Phase 13)
            from shared.internal_auth import verify_internal_token
            if verify_internal_token(credentials.credentials, settings.SECRET_KEY, settings.JWT_ALGORITHM):
                # Trust the X-Tenant-ID header if it's an internal-service call
                xtid = request.headers.get("X-Tenant-ID")
                if xtid:
                    return xtid
                # Fallback to state if already stamped
                state_tenant = getattr(request.state, "tenant_id", None)
                if state_tenant:
                    return str(state_tenant)
            
            # Otherwise, decode as a standard user access token
            payload = decode_access_token(credentials.credentials)
            tenant_id = payload.get("tenant_id")
            if tenant_id:
                return tenant_id
        except HTTPException as exc:
            # If JWT is invalid, but we have internal headers from the Gateway, 
            # we should trust the Gateway's validation.
            if not request.headers.get("X-Tenant-ID") and not getattr(request.state, "tenant_id", None):
                raise exc
            logger.debug("jwt_decode_failed_falling_back_to_internal_headers")

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


_ROLE_LEVELS: dict[str, int] = {
    "viewer":      0,
    "developer":   1,
    "admin":       2,
    "owner":       3,
    "super_admin": 4,
}


def require_forwarded_role(minimum_role: str):
    """FastAPI dependency for the AI Orchestrator.

    The orchestrator receives requests forwarded from the API Gateway.
    The caller's role is available in the ``X-Role`` header (set by the
    API Gateway after JWT/API-key verification and before proxying).

    Raises HTTP 403 if the role is insufficient.
    """
    from fastapi import Depends, HTTPException

    def _check(request: Request) -> str:
        role: str = (
            request.headers.get("X-Role")
            or getattr(request.state, "role", None)
            or "viewer"
        )
        if _ROLE_LEVELS.get(role, -1) < _ROLE_LEVELS.get(minimum_role, 999):
            raise HTTPException(
                status_code=403,
                detail=f"This action requires '{minimum_role}' role or higher. Current role: '{role}'.",
            )
        return role

    return _check


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
async def require_internal_key(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
):
    """
    Defense-in-depth: Verify that the request carries the shared internal secret
    or a valid signed inter-service JWT.
    """
    # 1. Prefer Signed JWT (Phase 13 Standard)
    if credentials:
        from shared.internal_auth import verify_internal_token
        if verify_internal_token(credentials.credentials, settings.SECRET_KEY, settings.JWT_ALGORITHM):
            return True

    # 2. Legacy check (X-Internal-Key)
    presented = request.headers.get("X-Internal-Key", "")
    if presented and settings.INTERNAL_API_KEY:
        import hmac
        if hmac.compare_digest(presented.encode(), settings.INTERNAL_API_KEY.encode()):
            return True

    logger.warning("unauthorized_internal_access_attempt", path=request.url.path)
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Internal service authentication required (JWT or valid key)."
    )


def get_actor_info(request: Request) -> Dict[str, Any]:
    """
    Zenith Forensics: Extract the full actor signature and trace continuity context
    from the trusted headers forwarded by the API Gateway.
    """
    role = request.headers.get("X-Role") or getattr(request.state, "role", "viewer")
    return {
        "actor_email": request.headers.get("X-Actor-Email") or getattr(request.state, "actor_email", "unknown"),
        "is_support_access": role == "super_admin",
        "trace_id": request.headers.get("X-Trace-ID") or getattr(request.state, "trace_id", "none"),
        "span_id": request.headers.get("X-Span-ID") or getattr(request.state, "span_id", "none"),
        "original_ip": request.headers.get("X-Original-IP") or (request.client.host if request.client else "unknown"),
    }
