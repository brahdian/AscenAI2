from __future__ import annotations
import time
from jose import jwt, JWTError
from fastapi import Header, HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.core.config import settings

security = HTTPBearer()

async def verify_internal_token(
    auth: HTTPAuthorizationCredentials = Depends(security)
) -> None:
    """
    Validates that the request contains a valid signed JWT internal token.
    Used for secure communication between AI Orchestrator and MCP Server.
    """
    token = auth.credentials
    try:
        payload = jwt.decode(
            token, 
            settings.SECRET_KEY, 
            algorithms=[settings.ALGORITHM]
        )
        
        # Verify specific internal claims
        if payload.get("sub") != "internal-service-call":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid token subject for internal call",
            )
            
        # Expiration is checked automatically by jose.jwt.decode
        
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired internal authentication token",
        )
