"""
Request/Response Validation Middleware

Logs all incoming requests and outgoing responses with structured data
for API contract validation and debugging.

Usage (in main.py):
    from app.core.validation_logging import ValidationLoggingMiddleware
    app.add_middleware(ValidationLoggingMiddleware)
"""
from __future__ import annotations

import json
import time
from typing import Optional

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = structlog.get_logger(__name__)

MAX_BODY_LOG_SIZE = 4096


def _safe_json_dumps(obj) -> str:
    try:
        return json.dumps(obj)
    except Exception:
        return "<serialization_error>"


class ValidationLoggingMiddleware(BaseHTTPMiddleware):
    """
    Logs request method, path, query params, content-type, and body summary
    before handling, and response status + latency after.
    
    Body is truncated to MAX_BODY_LOG_SIZE to avoid log flooding.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        method = request.method
        query_params = dict(request.query_params)
        content_type = request.headers.get("content-type", "")

        body = None
        if method in ("POST", "PUT", "PATCH"):
            try:
                raw_body = await request.body()
                if raw_body:
                    if len(raw_body) <= MAX_BODY_LOG_SIZE:
                        try:
                            body = json.loads(raw_body.decode("utf-8", errors="replace"))
                        except Exception:
                            body = raw_body.decode("utf-8", errors="replace")[:MAX_BODY_LOG_SIZE]
                    else:
                        body = f"<body_size:{len(raw_body)}>"
            except Exception:
                pass

        structlog.get_logger().info(
            "api_request_received",
            method=method,
            path=path,
            query_params=query_params,
            content_type=content_type,
            body=body,
        )

        t0 = time.monotonic()
        response = await call_next(request)
        latency_ms = int((time.monotonic() - t0) * 1000)

        structlog.get_logger().info(
            "api_response_sent",
            method=method,
            path=path,
            status_code=response.status_code,
            latency_ms=latency_ms,
        )

        return response