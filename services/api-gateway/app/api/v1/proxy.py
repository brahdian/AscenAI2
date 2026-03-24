from __future__ import annotations

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from app.core.config import settings

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/proxy")

# Downstream service URL map
_SERVICE_MAP = {
    "chat": settings.AI_ORCHESTRATOR_URL,
    "agents": settings.AI_ORCHESTRATOR_URL,
    "sessions": settings.AI_ORCHESTRATOR_URL,
    "tools": settings.MCP_SERVER_URL,
    "context": settings.MCP_SERVER_URL,
    "voice": settings.VOICE_PIPELINE_URL,
}

_TIMEOUT = httpx.Timeout(60.0, connect=5.0)


def _get_downstream_url(service: str, path: str) -> str:
    base = _SERVICE_MAP.get(service)
    if not base:
        raise HTTPException(status_code=404, detail=f"Unknown service: {service}")
    return f"{base}/api/v1/{service}{path}"


async def _proxy_request(request: Request, url: str) -> Response:
    """Forward a request to a downstream service and return the response."""
    # Forward auth headers plus tenant context
    headers = {
        "X-Tenant-ID": getattr(request.state, "tenant_id", ""),
        "X-User-ID": getattr(request.state, "user_id", ""),
        "X-Role": getattr(request.state, "role", ""),
        "X-Trace-ID": getattr(request.state, "trace_id", ""),
        "Content-Type": request.headers.get("Content-Type", "application/json"),
    }

    body = await request.body()

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.request(
                method=request.method,
                url=url,
                headers=headers,
                content=body,
                params=dict(request.query_params),
            )
    except httpx.ConnectError as exc:
        logger.error("proxy_connect_error", url=url, error=str(exc))
        raise HTTPException(status_code=503, detail="Downstream service unavailable.")
    except httpx.TimeoutException as exc:
        logger.error("proxy_timeout", url=url, error=str(exc))
        raise HTTPException(status_code=504, detail="Downstream service timed out.")

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers={
            k: v
            for k, v in resp.headers.items()
            if k.lower() not in ("content-encoding", "transfer-encoding", "connection")
        },
    )


@router.api_route(
    "/{service}/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def proxy(service: str, path: str, request: Request) -> Response:
    """Generic reverse proxy to downstream services."""
    url = _get_downstream_url(service, f"/{path}" if path else "")
    return await _proxy_request(request, url)
