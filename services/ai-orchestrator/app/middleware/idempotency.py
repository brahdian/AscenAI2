"""
Framework-wide idempotency middleware for the AI Orchestrator.

If a request carries an `Idempotency-Key` header and the same key was seen
within the TTL window (default 24 h), the cached response is returned
immediately without re-executing the handler.

Key format:  idempotency:{tenant_id}:{method}:{path}:{key}
Tenant scope:  Two tenants with the same Idempotency-Key get independent
               cached responses (no cross-tenant leakage).

Notes:
- Only POST / PUT / PATCH methods are considered (GET/DELETE are safe).
- The header is optional — absence means no caching.
- If Redis is unavailable the request is processed normally (fail-open).
- Chat-specific idempotency (5-min TTL) is still handled in chat.py;
  this middleware provides a 24-h safety net for all other mutations.
"""

from __future__ import annotations

import json
import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse

logger = structlog.get_logger(__name__)

_IDEMPOTENCY_HEADER = "Idempotency-Key"
_IDEMPOTENCY_TTL = 86_400  # 24 hours in seconds
_APPLICABLE_METHODS = frozenset({"POST", "PUT", "PATCH"})
_EXEMPT_PATHS = frozenset({
    "/api/v1/chat",
    "/api/v1/chat/stream",
    "/health",
    "/metrics",
})


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """Cache mutation responses keyed by tenant + Idempotency-Key header."""

    async def dispatch(self, request: Request, call_next) -> Response:
        # Only applicable to mutating methods
        if request.method not in _APPLICABLE_METHODS:
            return await call_next(request)

        # Skip exempt paths (chat has its own idempotency layer)
        path = request.url.path
        if any(path.startswith(ep) for ep in _EXEMPT_PATHS):
            return await call_next(request)

        idempotency_key = request.headers.get(_IDEMPOTENCY_HEADER)
        if not idempotency_key or len(idempotency_key) > 128:
            return await call_next(request)

        tenant_id = getattr(request.state, "tenant_id", None)
        if not tenant_id:
            return await call_next(request)

        redis = getattr(getattr(request, "app", None), "state", None)
        redis = getattr(redis, "redis", None) if redis else None
        if redis is None:
            return await call_next(request)

        cache_key = f"idempotency:{tenant_id}:{request.method}:{path}:{idempotency_key}"

        # Check cache
        try:
            cached = await redis.get(cache_key)
            if cached:
                payload = json.loads(cached)
                logger.info(
                    "idempotency_cache_hit",
                    path=path,
                    method=request.method,
                    key=idempotency_key,
                    tenant_id=tenant_id,
                )
                return JSONResponse(
                    content=payload["body"],
                    status_code=payload["status_code"],
                    headers={"X-Idempotency-Replayed": "true"},
                )
        except Exception as exc:
            logger.warning("idempotency_cache_read_error", error=str(exc))

        # Process request
        response = await call_next(request)

        # Cache successful responses (2xx) only
        if 200 <= response.status_code < 300:
            try:
                body_bytes = b""
                async for chunk in response.body_iterator:
                    body_bytes += chunk

                body_text = body_bytes.decode("utf-8", errors="replace")
                try:
                    body_json = json.loads(body_text)
                except (json.JSONDecodeError, ValueError):
                    body_json = body_text

                payload = json.dumps({
                    "status_code": response.status_code,
                    "body": body_json,
                })
                await redis.setex(cache_key, _IDEMPOTENCY_TTL, payload)

                # Reconstruct a proper response since we consumed the iterator
                return Response(
                    content=body_bytes,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    media_type=response.media_type,
                )
            except Exception as exc:
                logger.warning("idempotency_cache_write_error", error=str(exc))
                # Re-return the original response (best effort)
                return Response(
                    content=body_bytes if "body_bytes" in dir() else b"",
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    media_type=response.media_type,
                )

        return response
