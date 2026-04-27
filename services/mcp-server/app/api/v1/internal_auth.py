from __future__ import annotations
import time
from jose import jwt, JWTError
from fastapi import Header, HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.core.config import settings

from shared.internal_auth import verify_internal_token

security = HTTPBearer()

async def verify_internal_token(
    auth: HTTPAuthorizationCredentials = Depends(security)
) -> None:
    """
    Validates that the request contains a valid signed JWT internal token.
    Used for secure communication between AI Orchestrator and MCP Server.
    """
    token = auth.credentials
    if not verify_internal_token(token, settings.SECRET_KEY, getattr(settings, "ALGORITHM", "HS256")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired internal authentication token",
        )

