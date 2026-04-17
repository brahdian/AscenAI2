"""
Redis sliding-window rate limiter middleware for the API Gateway.
=================================================================
Implements a true sliding-window algorithm using a Redis sorted set:
  - Each request is recorded as a member with score = arrival timestamp.
  - Members older than WINDOW_SECONDS are pruned with ZREMRANGEBYSCORE.
  - The current count is ZCARD after pruning.
  - The key expires automatically after WINDOW_SECONDS with no new traffic.

M-2 fix: The previous implementation used INCR + EXPIREAT, which is a
fixed-window algorithm.  At a window boundary a client could make 2×LIMIT
requests in a short burst (LIMIT at the end of one window + LIMIT at the
start of the next).  The sorted-set approach eliminates this vulnerability
because the window always looks back exactly WINDOW_SECONDS from now.

Configuration (env vars):
    RATE_LIMIT_REQUESTS  = 120   # requests per window (default: 120/min)
    RATE_LIMIT_WINDOW_SECONDS = 60

Headers returned on every response:
    X-RateLimit-Limit     : configured limit
    X-RateLimit-Remaining : remaining requests in the current window
    X-RateLimit-Reset     : epoch seconds when the window will next reset

Endpoints exempt from rate limiting (health probes, Stripe webhooks):
    /health* , /metrics , /api/v1/billing/webhook
"""
from __future__ import annotations

import time
import uuid
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

# Lua script: atomic sliding-window check-and-record.
# Returns {current_count, window_reset_epoch}
_SLIDING_WINDOW_LUA = """
local key        = KEYS[1]
local now        = tonumber(ARGV[1])
local window     = tonumber(ARGV[2])
local member     = ARGV[3]
local cutoff     = now - window

-- Remove entries older than the window
redis.call('ZREMRANGEBYSCORE', key, '-inf', cutoff)

-- Add current request
redis.call('ZADD', key, now, member)

-- Set TTL so the key auto-expires when idle
redis.call('EXPIRE', key, window + 1)

-- Count requests in current window
local count = redis.call('ZCARD', key)

return {count, math.ceil(now / window) * window}
"""


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Per-tenant (falling back to per-IP) true sliding-window rate limiter.

    Parameters
    ----------
    app:
        The ASGI application to wrap.
    limit:
        Maximum number of requests per window.
    window_seconds:
        Duration of the sliding window in seconds.
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
        key = f"rl_sw:{identifier}"
        now = time.time()
        # Unique member per request so simultaneous requests don't overwrite each other
        member = f"{now:.6f}:{uuid.uuid4().hex[:8]}"

        try:
            result = await redis.eval(
                _SLIDING_WINDOW_LUA,
                1,       # number of keys
                key,
                str(now),
                str(self.window),
                member,
            )
            current_count = int(result[0])
            window_reset = int(result[1])
        except Exception as exc:
            logger.warning("rate_limit_redis_error", error=str(exc), path=path)
            # Fail open — don't block legitimate traffic during Redis outage
            return await call_next(request)

        remaining = max(0, self.limit - current_count)
        headers = {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Reset": str(window_reset),
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
                    "retry_after": max(1, window_reset - int(now)),
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
