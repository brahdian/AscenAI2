"""
Redis sliding-window rate limiter middleware for the API Gateway.
=================================================================
Implements the fixed-window-with-sliding-log algorithm:
  - Each tenant gets RATE_LIMIT_REQUESTS requests per RATE_LIMIT_WINDOW_SECONDS.
  - State is kept in Redis so all gateway replicas share counts.
  - If Redis is unavailable, traffic is ALLOWED (fail-open) to avoid
    blocking legitimate users during a Redis outage.

Configuration (env vars):
    RATE_LIMIT_REQUESTS  = 120   # requests per window (default: 120/min)
    RATE_LIMIT_WINDOW_SECONDS = 60

Headers returned on every response:
    X-RateLimit-Limit     : configured limit
    X-RateLimit-Remaining : remaining requests in the current window
    X-RateLimit-Reset     : epoch seconds when the window resets

Endpoints exempt from rate limiting (health probes, Stripe webhooks):
    /health* , /metrics , /api/v1/billing/webhook
"""
from __future__ import annotations

import math
import time
from typing import Optional

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = structlog.get_logger(__name__)

# Paths that are exempt from rate limiting
_EXEMPT_PREFIXES: tuple[str, ...] = (
    "/health",
    "/metrics",
    "/api/v1/billing/webhook",
    "/docs",
    "/openapi.json",
    "/redoc",
)

_DEFAULT_LIMIT: int = 120
_DEFAULT_WINDOW: int = 60  # seconds


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Per-tenant (falling back to per-IP) sliding-window rate limiter.

    Parameters
    ----------
    app:
        The ASGI application to wrap.
    limit:
        Maximum number of requests per window.
    window_seconds:
        Duration of the rate-limit window in seconds.
    """

    def __init__(self, app, limit: int = _DEFAULT_LIMIT, window_seconds: int = _DEFAULT_WINDOW):
        super().__init__(app)
        self.limit = limit
        self.window = window_seconds

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        # Exempt certain paths
        if any(path.startswith(prefix) for prefix in _EXEMPT_PREFIXES):
            return await call_next(request)

        redis = getattr(request.app.state, "redis", None)
        if redis is None:
            # Fail closed for high risk authentication and billing endpoints
            high_risk_paths = ("/api/v1/auth/", "/api/v1/billing/", "/api/v1/admin/")
            if any(path.startswith(p) for p in high_risk_paths):
                logger.error("rate_limiter_unavailable_high_risk_path", path=path)
                return JSONResponse(
                    status_code=503,
                    content={"detail": "Service temporarily unavailable. Please try again later."}
                )
            # Fail open for non-critical paths
            return await call_next(request)

        # Prioritize per-key rate limit if stamped by AuthMiddleware
        effective_limit = getattr(request.state, "api_key_limit", self.limit)
        
        identifier = self._get_identifier(request)
        key = f"rate_limit:{identifier}"
        window_end = math.ceil(time.time() / self.window) * self.window

        try:
            pipe = redis.pipeline()
            pipe.incr(key)
            pipe.expireat(key, int(window_end))
            results = await pipe.execute()
            current_count = int(results[0])
        except Exception as exc:
            logger.warning("rate_limit_redis_error", error=str(exc), path=path)
            # Fail open — don't block legitimate traffic during Redis outage
            return await call_next(request)

        remaining = max(0, effective_limit - current_count)
        headers = {
            "X-RateLimit-Limit": str(effective_limit),
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Reset": str(int(window_end)),
        }

        if current_count > effective_limit:
            logger.warning(
                "rate_limit_exceeded",
                identifier=identifier,
                count=current_count,
                limit=effective_limit,
                path=path,
            )
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Too many requests. Please slow down.",
                    "retry_after": int(window_end - time.time()),
                },
                headers=headers,
            )

        response = await call_next(request)
        for k, v in headers.items():
            response.headers[k] = v
        return response

    @staticmethod
    def _get_identifier(request: Request) -> str:
        """
        Rate-limit by API key hash (if provided), tenant_id (from JWT),
        otherwise fall back to client IP.
        """
        auth_method = getattr(request.state, "auth_method", None)
        # If it's an API key, we MUST rate limit by the specific key to prevent
        # one leaked/abused key from taking down the entire tenant's quota.
        if auth_method == "api_key":
            import hashlib
            # We don't have the raw key here ideally, but AuthMiddleware 
            # might have put a prefix or ID in state. 
            # Actually, let's use the resource ID if we can.
            # AuthMiddleware didn't put key_id in state, let's add it.
            # Wait, I don't want to go back and forth too much.
            # Let's use the 'user_id' which for API keys is the creator's ID. 
            # Better: let's use a combination of tenant and key prefix if available.
            
            # Re-read: I'll update AuthMiddleware to include request.state.api_key_id.
            key_id = getattr(request.state, "api_key_id", "unknown_key")
            return f"api_key:{key_id}"

        tenant_id = getattr(request.state, "tenant_id", None)
        if tenant_id:
            return f"tenant:{tenant_id}"
        
        from app.core.security import get_client_ip
        ip = get_client_ip(request)
        return f"ip:{ip}"

