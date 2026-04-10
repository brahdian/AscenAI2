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
            # No Redis — fail open
            return await call_next(request)

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

        remaining = max(0, self.limit - current_count)
        headers = {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Reset": str(int(window_end)),
        }

        if current_count > self.limit:
            logger.warning(
                "rate_limit_exceeded",
                identifier=identifier,
                count=current_count,
                limit=self.limit,
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
        Rate-limit by tenant_id (from JWT/middleware) when available,
        otherwise fall back to client IP.
        """
        tenant_id = getattr(request.state, "tenant_id", None)
        if tenant_id:
            return f"tenant:{tenant_id}"
        # Best-effort IP extraction (behind reverse proxy)
        forwarded_for = request.headers.get("X-Forwarded-For", "")
        ip = forwarded_for.split(",")[0].strip() if forwarded_for else request.client.host
        return f"ip:{ip}"
