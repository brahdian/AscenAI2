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

        # ── Pillar 1: Forensic Traceability (Identity Binding) ─────────────
        # Bind identity to the logging context so every log entry for this
        # request includes the actor and tenant.
        structlog.contextvars.bind_contextvars(
            user_id=getattr(request.state, "user_id", None),
            tenant_id=getattr(request.state, "tenant_id", None),
            actor_email=getattr(request.state, "actor_email", None),
            is_support_access=getattr(request.state, "is_support_access", False),
        )

        # ── Pillar 3: Zero-Trust Perimeter (Agent Isolation) ──────────────
        # If X-Restricted-Agent-ID is provided, verify it against the auth context.
        # This prevents lateral movement even if a session is compromised.
        restricted_agent_id = request.headers.get("X-Restricted-Agent-ID")
        if restricted_agent_id:
            # API Keys restricted to a specific agent cannot access others
            key_agent_id = getattr(request.state, "api_key_agent_id", None)
            if key_agent_id and key_agent_id != restricted_agent_id:
                logger.warning("auth_agent_isolation_violation", path=request.url.path, 
                               requested=restricted_agent_id, key_restricted_to=key_agent_id)
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Access denied: request restricted to a different agent context."}
                )
            request.state.restricted_agent_id = restricted_agent_id

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
                        # ── Session version enforcement (Cache) ──────────────
                        token_version = payload.get("version")
                        cached_version = entry.get("session_version")
                        
                        if token_version is not None and cached_version is not None:
                            if token_version != cached_version:
                                logger.info("auth_session_version_mismatch_cached", user_id=user_id)
                                return False

                        # ── Tenant status enforcement (Cache - Phase 16) ──────
                        # Ensure suspended tenants cannot access the console/API
                        # Explicit naming for Zenith Pillar 5 compliance.
                        entry_status = entry.get("tenant_activation_status", "active")
                        if entry_status == "suspended" or entry.get("tenant_is_active") is False:
                            logger.warning("auth_tenant_suspended_cached", tenant_id=tenant_id)
                            return False

                        request.state.user_id = user_id
                        request.state.tenant_id = tenant_id
                        request.state.role = entry.get("role", role)
                        request.state.actor_email = entry.get("email") or "system"
                        request.state.is_support_access = entry.get("is_support_access", False)
                        request.state.tenant_activation_status = "active"
                        request.state.auth_method = "jwt"
                        return True

                except Exception as exc:
                    logger.warning("auth_cache_read_error", error=str(exc))

            # ── DB verification (cache miss) ──────────────────────────────────
            async with AsyncSessionLocal() as db:
                user_res = await db.execute(
                    select(User).where(User.id == uuid.UUID(user_id))
                )
                user = user_res.scalar_one_or_none()
                if not user or not user.is_active:
                    return False

                token_version = payload.get("version")
                if token_version is not None and token_version != user.session_version:
                    logger.info(
                        "auth_session_version_mismatch",
                        user_id=user_id,
                        token_version=token_version,
                        db_version=user.session_version,
                    )
                    return False

                tenant_res = await db.execute(
                    select(Tenant).where(Tenant.id == uuid.UUID(tenant_id))
                )
                tenant = tenant_res.scalar_one_or_none()
                if not tenant or not tenant.is_active:
                    return False

            # Support Access: Check payload claim (e.g. from Google internal SSO or specialized JWT)
            is_support = payload.get("is_support", False)

            # Populate cache
            if redis:
                try:
                    await redis.setex(
                        cache_key,
                        _AUTH_CACHE_TTL,
                        json.dumps({
                            "role": role, 
                            "email": user.email,
                            "session_version": user.session_version,
                            "tenant_activation_status": "active" if tenant.is_active else "suspended",
                            "is_support_access": is_support
                        }),
                    )
                except Exception as exc:
                    logger.warning("auth_cache_write_error", error=str(exc))

            request.state.user_id = user_id
            request.state.tenant_id = tenant_id
            request.state.role = role
            request.state.actor_email = user.email
            request.state.is_support_access = is_support
            request.state.tenant_activation_status = "active"
            request.state.auth_method = "jwt"
            return True

        except (JWTError, ValueError) as exc:
            logger.warning("jwt_decode_failed", error=str(exc))
            return False

    async def _authenticate_api_key(self, request: Request, raw_key: str) -> bool:
        import hashlib
        from datetime import datetime, timezone
        import json

        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        
        # ── Redis auth cache (Phase 10) ──────────────────────────────────
        # API Keys are now cached to reduce DB load, parity with JWTs.
        cache_key = f"auth:api_key:{key_hash}"
        redis = await _get_redis()
        if redis:
            try:
                cached = await redis.get(cache_key)
                if cached:
                    entry = json.loads(cached)
                    entry_status = entry.get("tenant_activation_status", "active")
                    if entry_status == "suspended" or entry.get("tenant_is_active") is False:
                        logger.warning("auth_api_key_tenant_suspended_cached", tenant_id=entry.get("tenant_id"))
                        return False

                    request.state.user_id = entry.get("user_id")
                    request.state.tenant_id = entry.get("tenant_id")
                    request.state.role = entry.get("role", "developer")
                    request.state.actor_email = entry.get("email")
                    request.state.auth_method = "api_key"
                    request.state.api_key_id = entry.get("api_key_id")
                    request.state.api_key_scopes = entry.get("scopes", [])
                    request.state.api_key_agent_id = entry.get("agent_id")
                    request.state.api_key_limit = entry.get("rate_limit", 60)
                    request.state.is_support_access = False # API Keys are never support access
                    request.state.tenant_activation_status = entry_status
                    return True
            except Exception as exc:
                logger.warning("api_key_cache_read_error", error=str(exc))

        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(APIKey, User).join(User, APIKey.user_id == User.id).where(
                        APIKey.key_hash == key_hash,
                        APIKey.is_active.is_(True),
                    )
                )
                res = result.one_or_none()
                if res is None:
                    return False

                api_key, user = res

                # Ensure tenant is active for API keys too
                tenant_res = await db.execute(
                    select(Tenant).where(Tenant.id == api_key.tenant_id)
                )
                tenant = tenant_res.scalar_one_or_none()
                if not tenant or not tenant.is_active:
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

                # Populate cache
                if redis:
                    try:
                        cache_data = {
                            "user_id": str(api_key.user_id),
                            "tenant_id": str(api_key.tenant_id),
                            "role": "developer",
                            "email": user.email,
                            "api_key_id": str(api_key.id),
                            "scopes": api_key.scopes,
                            "agent_id": str(api_key.agent_id) if api_key.agent_id else None,
                            "rate_limit": api_key.rate_limit_per_minute,
                            "tenant_activation_status": "active"
                        }
                        await redis.setex(cache_key, _AUTH_CACHE_TTL, json.dumps(cache_data))
                    except Exception as exc:
                        logger.warning("api_key_cache_write_error", error=str(exc))

                # -- Origin Validation (Domain Lockdown) --
                # MUST be inside the async-with block so:
                #   1. `db` is still open for the audit_log write.
                #   2. request.state is NOT pre-populated before a denial --
                #      a denied origin must never receive an authenticated context.
                if api_key.allowed_origins:
                    origin = request.headers.get("Origin")
                    if not origin:
                        referer = request.headers.get("Referer")
                        if referer:
                            from urllib.parse import urlparse
                            try:
                                p = urlparse(referer)
                                origin = f"{p.scheme}://{p.netloc}"
                            except Exception:
                                pass

                    if not origin or origin.rstrip("/") not in [o.rstrip("/") for o in api_key.allowed_origins]:
                        from app.services.audit_service import audit_log
                        await audit_log(
                            db=db,
                            action="auth.api_key_origin_denied",
                            tenant_id=str(api_key.tenant_id),
                            user_id=str(api_key.user_id),
                            category="security",
                            resource_type="api_key",
                            resource_id=str(api_key.id),
                            status="failure",
                            details={
                                "requested_origin": origin,
                                "key_prefix": api_key.key_prefix,
                                "path": request.url.path,
                            },
                        )
                        logger.warning(
                            "auth_api_key_origin_denied",
                            tenant_id=str(api_key.tenant_id),
                            key_prefix=api_key.key_prefix,
                            requested_origin=origin,
                        )
                        return False

            # Origin validated (or not restricted). Safe to populate request.state.
            request.state.user_id = str(api_key.user_id)
            request.state.tenant_id = str(api_key.tenant_id)
            request.state.role = "developer"
            request.state.actor_email = user.email
            request.state.auth_method = "api_key"
            request.state.api_key_id = str(api_key.id)
            request.state.api_key_scopes = api_key.scopes
            request.state.api_key_agent_id = str(api_key.agent_id) if api_key.agent_id else None
            request.state.api_key_limit = api_key.rate_limit_per_minute
            request.state.is_support_access = False
            request.state.tenant_activation_status = "active"
            return True
        except Exception as exc:
            logger.error("api_key_lookup_failed", error=str(exc))
            return False
