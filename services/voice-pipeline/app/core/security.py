from typing import Optional
from jose import JWTError, jwt
from fastapi import HTTPException, status
import structlog

from app.core.config import settings

logger = structlog.get_logger(__name__)


def decode_access_token(token: str) -> dict:
    """Decode and validate JWT token, return payload dict."""
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


def validate_token_for_tenant(token: str, tenant_id: str) -> dict:
    """Decode token and verify it matches the given tenant_id."""
    payload = decode_access_token(token)
    token_tenant: Optional[str] = payload.get("tenant_id")
    if not token_tenant:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing tenant_id claim",
        )
    if token_tenant != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token tenant_id does not match requested tenant",
        )
    return payload
