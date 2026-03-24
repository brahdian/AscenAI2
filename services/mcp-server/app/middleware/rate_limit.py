import time
from typing import Optional

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse

from app.core.config import settings

logger = structlog.get_logger(__name__)

# Paths that are exempt from rate limiting
RATE_LIMIT_SKIP_PATHS = {
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/metrics",
}


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Sliding-window rate limiter using Redis.

    Key format:  rate_limit:{tenant_id}:{window_bucket}
    Window:      settings.RATE_LIMIT_WINDOW_SECONDS  (default 60s)
    Limit:       settings.RATE_LIMIT_PER_MINUTE  requests per window

    Uses a sorted set per (tenant, window) to count unique request timestamps
    within the current sliding window.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        path = request.url.path

        if path in RATE_LIMIT_SKIP_PATHS or path.startswith("/metrics"):
            return await call_next(request)

        tenant_id: Optional[str] = getattr(request.state, "tenant_id", None)
        if not tenant_id:
            # Tenant middleware hasn't set it yet (shouldn't happen in normal flow)
            return await call_next(request)

        redis = getattr(request.app.state, "redis", None)
        if redis is None:
            # Redis not available — allow request through (fail open)
            logger.warning("rate_limit_redis_unavailable", tenant_id=tenant_id)
            return await call_next(request)

        allowed, remaining, reset_in = await self._check_rate_limit(
            redis, tenant_id
        )

        if not allowed:
            logger.warning(
                "rate_limit_exceeded",
                tenant_id=tenant_id,
                path=path,
                limit=settings.RATE_LIMIT_PER_MINUTE,
            )
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Rate limit exceeded",
                    "limit": settings.RATE_LIMIT_PER_MINUTE,
                    "reset_in_seconds": reset_in,
                },
                headers={
                    "X-RateLimit-Limit": str(settings.RATE_LIMIT_PER_MINUTE),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(time.time()) + reset_in),
                    "Retry-After": str(reset_in),
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(settings.RATE_LIMIT_PER_MINUTE)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(
            int(time.time()) + settings.RATE_LIMIT_WINDOW_SECONDS
        )
        return response

    @staticmethod
    async def _check_rate_limit(
        redis, tenant_id: str
    ) -> tuple[bool, int, int]:
        """
        Sliding window algorithm using Redis sorted sets.

        Returns:
            (allowed, remaining, reset_in_seconds)
        """
        window = settings.RATE_LIMIT_WINDOW_SECONDS
        limit = settings.RATE_LIMIT_PER_MINUTE
        now = time.time()
        window_start = now - window
        key = f"rate_limit:{tenant_id}"
        member = str(now)

        pipe = redis.pipeline()
        # Remove members outside the current window
        pipe.zremrangebyscore(key, "-inf", window_start)
        # Add current request with timestamp as score
        pipe.zadd(key, {member: now})
        # Count requests in the window
        pipe.zcard(key)
        # Set expiry on the key
        pipe.expire(key, window)
        results = await pipe.execute()

        current_count: int = results[2]
        remaining = max(0, limit - current_count)
        allowed = current_count <= limit
        reset_in = int(window)
        return allowed, remaining, reset_in
