from __future__ import annotations

import json
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
from app.models.tenant import Tenant

logger = structlog.get_logger(__name__)

# Headers that must never appear in logs — always redact to "***".
_REDACT_HEADERS: frozenset[str] = frozenset({
    "authorization", "x-api-key", "cookie", "x-internal-key", "set-cookie",
})


def _sanitize_headers(headers) -> dict[str, str]:
    """Return a copy of *headers* with sensitive values replaced by '***'.

    Safe to pass to structlog — prevents credential leakage in access logs
    and error reports.
    """
    return {
        k: ("***" if k.lower() in _REDACT_HEADERS else v)
        for k, v in headers.items()
    }


# JWT auth cache TTL: 5 minutes.  Balances security (stale sessions noticed
# quickly) vs DB load (N requests per user only cost 1 DB round-trip per TTL).
_AUTH_CACHE_TTL = 300


async def _get_redis():
    """Return the shared Redis client, or None if unavailable."""
    try:
        from app.core.redis_client import get_redis
        return await get_redis()
    except Exception:
        return None

# Paths that don't require authentication
PUBLIC_PATHS = {
    "/health",
    "/metrics",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/api/v1/auth/register",
    "/api/v1/auth/login",
    "/api/v1/auth/verify-email",
    "/api/v1/auth/resend-otp",
    "/api/v1/auth/subscribe",
    "/api/v1/auth/me",
    "/api/v1/auth/refresh",
    "/api/v1/auth/forgot-password",
    "/api/v1/auth/reset-password",
    "/api/v1/billing/plans",
    "/api/v1/billing/webhook",
    "/api/v1/playbooks/validate-safety",
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
        if request.url.path.startswith("/api/v1/webhooks"):
            return await call_next(request)

        token: Optional[str] = None
        auth_header = request.headers.get("Authorization", "")
        auth_header_lower = auth_header.lower()

        if auth_header_lower.startswith("bearer "):
            token = auth_header[7:]
        elif auth_header_lower.startswith("apikey "):
            token = auth_header[7:]
        else:
            # Also check X-API-Key header
            token = request.headers.get("X-API-Key")

        # Fall back to HttpOnly cookie (set by login/register/refresh endpoints)
        if not token:
            token = request.cookies.get("access_token")

        if not token:
            from fastapi.responses import JSONResponse
            logger.info("auth_failed_missing_credentials", path=request.url.path,
                        headers=_sanitize_headers(request.headers))
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication required."},
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Try JWT first, then API key (depending on how the token was found)
        auth_header = request.headers.get("Authorization", "")
        is_api_key = auth_header.lower().startswith("apikey ") or request.headers.get("X-API-Key") is not None

        if is_api_key:
            ok = await self._authenticate_api_key(request, token)
        else:
            # Default to JWT for Bearer and Cookies
            ok = await self._authenticate_jwt(request, token)
            # Fallback to API key if JWT fails (handles cases where a key is passed without the right prefix)
            if not ok and not auth_header.lower().startswith("bearer "):
                ok = await self._authenticate_api_key(request, token)

        if not ok:
            from fastapi.responses import JSONResponse
            logger.warning("auth_failed_invalid_credentials", path=request.url.path,
                           headers=_sanitize_headers(request.headers))
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or expired credentials."},
                headers={"WWW-Authenticate": "Bearer"},
            )

        return await call_next(request)

    async def _authenticate_jwt(self, request: Request, token: str) -> bool:
        try:
            payload = jwt.decode(
                token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
            )
            if payload.get("type") != "access":
                return False

            user_id = payload.get("sub")
            tenant_id = payload.get("tenant_id")
            role = payload.get("role", "viewer")

            if not user_id or not tenant_id:
                return False

            # ── Redis auth cache ──────────────────────────────────────────────
            # Skip the two DB queries on every request when the answer is already
            # cached.  Cache key encodes both user and tenant so a user moved
            # between tenants is not served a stale entry.
            cache_key = f"auth:jwt:{user_id}:{tenant_id}"
            redis = await _get_redis()
            if redis:
                try:
                    cached = await redis.get(cache_key)
                    if cached:
                        entry = json.loads(cached)
                        request.state.user_id = user_id
                        request.state.tenant_id = tenant_id
                        request.state.role = entry.get("role", role)
                        request.state.auth_method = "jwt"
                        return True
                except Exception as exc:
                    logger.warning("auth_cache_read_error", error=str(exc))

            # ── DB verification (cache miss) ──────────────────────────────────
            # Verify that user and tenant still exist in the database.
            # This handles stale sessions after a 'make clean' or record deletion.
            async with AsyncSessionLocal() as db:
                user_res = await db.execute(
                    select(User).where(User.id == uuid.UUID(user_id))
                )
                user = user_res.scalar_one_or_none()
                if not user or not user.is_active:
                    return False

                tenant_res = await db.execute(
                    select(Tenant).where(Tenant.id == uuid.UUID(tenant_id))
                )
                tenant = tenant_res.scalar_one_or_none()
                if not tenant:
                    return False

            # Populate cache so subsequent requests skip the DB queries
            if redis:
                try:
                    await redis.setex(
                        cache_key,
                        _AUTH_CACHE_TTL,
                        json.dumps({"role": role}),
                    )
                except Exception as exc:
                    logger.warning("auth_cache_write_error", error=str(exc))

            request.state.user_id = user_id
            request.state.tenant_id = tenant_id
            request.state.role = role
            request.state.auth_method = "jwt"
            return True
        except (JWTError, ValueError) as exc:
            logger.warning("jwt_decode_failed", error=str(exc))
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
