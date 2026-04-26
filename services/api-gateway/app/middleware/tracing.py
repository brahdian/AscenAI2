from __future__ import annotations

import time
import uuid

import structlog
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

logger = structlog.get_logger(__name__)

class TracingMiddleware(BaseHTTPMiddleware):
    """
    Zenith Pillar 12: Observability & Debuggability
    
    Distributed tracing middleware that propagates trace IDs across all services.
    Adds X-Trace-ID, X-Span-ID, and X-Parent-Span-ID headers.
    """
    
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        
        # Extract or generate trace ID
        trace_id = request.headers.get("X-Trace-ID") or str(uuid.uuid4())
        span_id = str(uuid.uuid4())
        parent_span_id = request.headers.get("X-Span-ID")
        
        # Attach to request state
        request.state.trace_id = trace_id
        request.state.span_id = span_id
        request.state.parent_span_id = parent_span_id
        request.state.request_start_time = start_time
        
        # Add trace context to all outgoing requests
        original_headers = dict(request.headers)
        original_headers["X-Trace-ID"] = trace_id
        original_headers["X-Span-ID"] = span_id
        if parent_span_id:
            original_headers["X-Parent-Span-ID"] = parent_span_id
        
        # Process request
        response = await call_next(request)
        
        # Calculate duration
        duration_ms = int((time.time() - start_time) * 1000)
        
        # Add trace headers to response
        response.headers["X-Trace-ID"] = trace_id
        response.headers["X-Request-Duration-MS"] = str(duration_ms)
        
        # Structured request logging
        logger.info(
            "request_completed",
            trace_id=trace_id,
            path=request.url.path,
            method=request.method,
            status_code=response.status_code,
            duration_ms=duration_ms,
            user_agent=request.headers.get("User-Agent"),
            client_ip=request.client.host if request.client else None
        )
        
        return response


def propagate_trace_headers(request: Request) -> dict:
    """
    Get trace headers to propagate to downstream services.
    
    Usage:
        headers = propagate_trace_headers(request)
        await client.post(url, headers=headers)
    """
    headers = {}
    
    if hasattr(request.state, "trace_id"):
        headers["X-Trace-ID"] = request.state.trace_id
    if hasattr(request.state, "span_id"):
        headers["X-Span-ID"] = request.state.span_id
    
    headers["X-Original-IP"] = request.client.host if request.client else None
    
    return headers
