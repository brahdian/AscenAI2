import hashlib
import hmac
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
import structlog

from app.core.config import settings

logger = structlog.get_logger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer(auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def hash_api_key(api_key: str) -> str:
    """Hash an API key using SHA-256 for storage."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def verify_api_key_hash(plain_key: str, hashed_key: str) -> bool:
    """Verify a plain API key against its stored SHA-256 hash."""
    computed = hashlib.sha256(plain_key.encode("utf-8")).hexdigest()
    return hmac.compare_digest(computed, hashed_key)


def create_access_token(data: dict, expires_delta_minutes: Optional[int] = None) -> str:
    """Create a JWT access token."""
    from datetime import timedelta
    to_encode = data.copy()
    expire_minutes = expires_delta_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES
    expire = datetime.now(timezone.utc) + timedelta(minutes=expire_minutes)
    to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc)})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and verify a JWT token. Raises HTTPException on failure.

    Enforces:
    - Signature and expiry
    - Token type must be None or 'access' (refresh tokens rejected)
    - tenant_id claim must be a valid UUID
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])

        if payload.get("type") not in (None, "access"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Validate tenant_id claim format
        tenant_id = payload.get("tenant_id", "")
        if tenant_id:
            try:
                UUID(str(tenant_id))
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
            detail=f"Invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )


def extract_tenant_from_token(token: str) -> Optional[str]:
    """Extract tenant_id from JWT sub claim or tenant claim."""
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            options={"verify_exp": True},
        )
        # Support both 'tenant_id' claim and composite 'sub' like "tenant:{id}"
        tenant_id = payload.get("tenant_id")
        if tenant_id:
            return str(tenant_id)
        sub = payload.get("sub", "")
        if sub.startswith("tenant:"):
            return sub.split("tenant:", 1)[1]
        # sub may directly be the tenant_id UUID
        if sub == "internal-service-call":
            return None
        return sub if sub else None
    except JWTError:
        return None


def is_internal_token(token: str) -> bool:
    """Check if the token is a signed internal service call token."""
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            options={"verify_exp": True},
        )
        return payload.get("sub") == "internal-service-call"
    except JWTError:
        return False


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a bcrypt hash."""
    return pwd_context.verify(plain_password, hashed_password)


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return pwd_context.hash(password)


async def verify_api_key(
    api_key: Optional[str],
    db,
) -> Optional[str]:
    """
    Verify an API key and return the tenant_id if valid.
    Looks up the hashed key in the database.
    Returns tenant_id string or None if invalid.
    """
    if not api_key:
        return None
    from sqlalchemy import select, text
    hashed = hash_api_key(api_key)
    try:
        result = await db.execute(
            text(
                "SELECT tenant_id FROM api_keys WHERE key_hash = :key_hash AND is_active = true LIMIT 1"
            ),
            {"key_hash": hashed},
        )
        row = result.fetchone()
        if row:
            return str(row[0])
    except Exception as exc:
        logger.warning("api_key_lookup_failed", error=str(exc))
    return None


async def get_current_tenant(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    api_key: Optional[str] = Security(api_key_header),
) -> str:
    """
    FastAPI dependency: resolves tenant_id from Bearer token or API key.
    Raises 401 if neither is present or valid.
    """
    if credentials and credentials.credentials:
        tenant_id = extract_tenant_from_token(credentials.credentials)
        if tenant_id:
            return tenant_id

    if api_key:
        hashed = hash_api_key(api_key)
        # In the middleware we do DB lookup; here return sentinel for middleware resolution
        # The middleware should have already set tenant_id on request.state
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate API key without database context",
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
