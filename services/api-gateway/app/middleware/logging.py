from __future__ import annotations

import time

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.utils.pii import mask_pii as mask_sensitive_data

logger = structlog.get_logger(__name__)

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Structured access logging middleware.
    Integrates with TracingMiddleware to include trace_id and span_id in logs.
    Ensures query parameters are PII-masked before logging.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # Get tracing IDs set by TracingMiddleware
        trace_id = getattr(request.state, "trace_id", "unknown")
        
        start_time = time.perf_counter()
        
        # 1. Sanitize query params for logs (SOC2 compliance)
        sanitized_query = mask_sensitive_data(dict(request.query_params))
        
        logger.info(
            "request_started",
            trace_id=trace_id,
            method=request.method,
            path=request.url.path,
            query=sanitized_query,
            client_ip=request.client.host if request.client else "unknown",
        )

        try:
            response: Response = await call_next(request)
        except Exception:
            # Re-raise so global exception handler or outer middleware can catch it,
            # but we still want to log that the request "finished" with an error.
            raise
        finally:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            
            # Note: response might be None if an exception occurred and wasn't caught by a handler
            status_code = getattr(response, "status_code", 500) if 'response' in locals() else 500
            
            # ── Pillar 1: Forensic Traceability ──────────────────────────
            # Extract identity from state (set by AuthMiddleware) for the finish log.
            # This ensures that even if contextvars were cleared, the finish log has it.
            logger.info(
                "request_finished",
                trace_id=trace_id,
                method=request.method,
                path=request.url.path,
                status_code=status_code,
                duration_ms=duration_ms,
                tenant_id=getattr(request.state, "tenant_id", None),
                actor_email=getattr(request.state, "actor_email", None),
                is_support_access=getattr(request.state, "is_support_access", False),
            )

        # Inject timing headers
        response.headers["X-Response-Time"] = f"{duration_ms}ms"
        # Pillar 4: Operational Resilience — Silent stdout (Logs are JSON)
        return response
