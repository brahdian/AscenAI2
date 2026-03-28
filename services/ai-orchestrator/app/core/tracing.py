"""
Distributed tracing middleware.

Propagates W3C traceparent headers across all service boundaries so the
full request chain (api-gateway → ai-orchestrator → voice-pipeline) is
visible in any OTEL-compatible observability backend.

Usage (in each service's main.py):
    from app.core.tracing import TracingMiddleware
    app.add_middleware(TracingMiddleware)
"""
from __future__ import annotations

import re
import time
import uuid
from typing import Optional

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = structlog.get_logger(__name__)

# W3C traceparent: version-traceid-parentid-flags
_TRACEPARENT_RE = re.compile(
    r"^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$"
)
_TRACE_ID_KEY = "trace_id"
_SPAN_ID_KEY = "span_id"


def _new_trace_id() -> str:
    return uuid.uuid4().hex + uuid.uuid4().hex[:16]  # 32 hex chars


def _new_span_id() -> str:
    return uuid.uuid4().hex[:16]  # 16 hex chars


def _make_traceparent(trace_id: str, span_id: str) -> str:
    return f"00-{trace_id}-{span_id}-01"


def _parse_traceparent(header: str) -> Optional[tuple[str, str]]:
    """Return (trace_id, parent_span_id) or None if invalid."""
    m = _TRACEPARENT_RE.match(header.strip().lower())
    if not m:
        return None
    return m.group(1), m.group(2)


class TracingMiddleware(BaseHTTPMiddleware):
    """
    - Reads incoming W3C traceparent header (from api-gateway or upstream)
    - Generates a new trace_id if none present
    - Stores trace_id + span_id on request.state for structured logging
    - Adds traceparent + X-Trace-ID response headers
    - Records request latency via structlog
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        incoming = request.headers.get("traceparent", "")
        parsed = _parse_traceparent(incoming) if incoming else None

        if parsed:
            trace_id, _ = parsed
        else:
            trace_id = _new_trace_id()

        span_id = _new_span_id()

        # Expose on request.state so route handlers can read them
        request.state.trace_id = trace_id
        request.state.span_id = span_id

        # Bind to structlog context for this request
        structlog.contextvars.bind_contextvars(
            trace_id=trace_id,
            span_id=span_id,
        )

        t0 = time.monotonic()
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.unbind_contextvars(_TRACE_ID_KEY, _SPAN_ID_KEY)

        latency_ms = int((time.monotonic() - t0) * 1000)
        response.headers["traceparent"] = _make_traceparent(trace_id, span_id)
        response.headers["X-Trace-ID"] = trace_id
        response.headers["X-Request-Latency-Ms"] = str(latency_ms)
        return response
