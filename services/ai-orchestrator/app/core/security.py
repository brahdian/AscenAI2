from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator, Optional, Tuple
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.core.config import settings

logger = structlog.get_logger(__name__)

security = HTTPBearer(auto_error=False)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
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
    Extract tenant_id. 
    Prioritizes JWT decoding if Bearer token is present.
    Falls back to X-Tenant-ID header injected by API Gateway.
    """
    if credentials:
        try:
            payload = decode_access_token(credentials.credentials)
            tenant_id = payload.get("tenant_id")
            if tenant_id:
                return tenant_id
        except HTTPException:
            pass # Fall back to header or let it fail below

    tenant_id = request.headers.get("x-tenant-id")
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return tenant_id


async def get_optional_tenant(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[str]:
    """Extract optional tenant_id from JWT or X-Tenant-ID header."""
    if credentials:
        try:
            payload = decode_access_token(credentials.credentials)
            return payload.get("tenant_id")
        except HTTPException:
            pass
    return request.headers.get("x-tenant-id")


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
