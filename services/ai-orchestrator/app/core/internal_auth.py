from __future__ import annotations

import time
from jose import jwt
from app.core.config import settings

def generate_internal_token() -> str:
    """
    Generate a short-lived (60s) JWT for inter-service authentication.
    Signed using the system-wide SECRET_KEY.
    """
    payload = {
        "iss": "ai-orchestrator",
        "sub": "internal-service-call",
        "iat": int(time.time()),
        "exp": int(time.time()) + 60,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def verify_internal_token(token: str) -> bool:
    """
    Verify a JWT for inter-service calls.
    Returns True if valid, False otherwise.
    """
    try:
        payload = jwt.decode(
            token, 
            settings.SECRET_KEY, 
            algorithms=[settings.JWT_ALGORITHM]
        )
        return payload.get("sub") == "internal-service-call"
    except Exception:
        return False
