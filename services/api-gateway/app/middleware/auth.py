from __future__ import annotations

import uuid
from typing import Optional

import structlog
from fastapi import Request, Response
from jose import JWTError, jwt
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.user import APIKey, User

logger = structlog.get_logger(__name__)

# Paths that don't require authentication
PUBLIC_PATHS = {
    "/health",
    "/metrics",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/api/v1/auth/register",
    "/api/v1/auth/login",
    "/api/v1/auth/refresh",
    "/api/v1/auth/forgot-password",
    "/api/v1/auth/reset-password",
}


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Extracts and validates JWT Bearer tokens or API keys.
    Sets request.state.user_id, request.state.tenant_id, request.state.role.
    Public paths are allowed through without authentication.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # Allow public paths and OPTIONS (preflight)
        if request.method == "OPTIONS" or request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        # Allow webhook paths (verified by signature in the router)
        if request.url.path.startswith("/api/v1/webhooks/inbound"):
            return await call_next(request)

        token: Optional[str] = None
        auth_header = request.headers.get("Authorization", "")

        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
        elif auth_header.startswith("ApiKey "):
            token = auth_header[7:]
        else:
            # Also check X-API-Key header
            token = request.headers.get("X-API-Key")

        if not token:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication required."},
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Try JWT first, then API key
        if token.startswith("sk_"):
            ok = await self._authenticate_api_key(request, token)
        else:
            ok = self._authenticate_jwt(request, token)

        if not ok:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or expired credentials."},
                headers={"WWW-Authenticate": "Bearer"},
            )

        return await call_next(request)

    def _authenticate_jwt(self, request: Request, token: str) -> bool:
        try:
            payload = jwt.decode(
                token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
            )
            if payload.get("type") != "access":
                return False
            request.state.user_id = payload.get("sub")
            request.state.tenant_id = payload.get("tenant_id")
            request.state.role = payload.get("role", "viewer")
            request.state.auth_method = "jwt"
            return True
        except JWTError as exc:
            logger.debug("jwt_validation_failed", error=str(exc))
            return False

    async def _authenticate_api_key(self, request: Request, raw_key: str) -> bool:
        import hashlib
        from datetime import datetime, timezone

        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(APIKey).where(
                        APIKey.key_hash == key_hash,
                        APIKey.is_active.is_(True),
                    )
                )
                api_key: Optional[APIKey] = result.scalar_one_or_none()

                if api_key is None:
                    return False

                now = datetime.now(timezone.utc)
                if api_key.expires_at and api_key.expires_at < now:
                    return False

                # Best-effort update last_used_at
                api_key.last_used_at = now
                try:
                    await db.commit()
                except Exception:
                    await db.rollback()

                request.state.user_id = str(api_key.user_id)
                request.state.tenant_id = str(api_key.tenant_id)
                request.state.role = "developer"
                request.state.auth_method = "api_key"
                request.state.api_key_scopes = api_key.scopes
                return True
        except Exception as exc:
            logger.error("api_key_lookup_failed", error=str(exc))
            return False
