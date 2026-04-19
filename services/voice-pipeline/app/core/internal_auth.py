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
        "iss": "voice-pipeline",
        "sub": "internal-service-call",
        "iat": int(time.time()),
        "exp": int(time.time()) + 60,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
