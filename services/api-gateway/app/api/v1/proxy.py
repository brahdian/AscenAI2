from __future__ import annotations

import json as _json

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
    "feedback": settings.AI_ORCHESTRATOR_URL,
    "analytics": settings.AI_ORCHESTRATOR_URL,
    "tools": settings.MCP_SERVER_URL,
    "context": settings.MCP_SERVER_URL,
    "voice": settings.VOICE_PIPELINE_URL,
}

_TIMEOUT = httpx.Timeout(60.0, connect=5.0)

# Fields that clients must never be allowed to inject into downstream requests.
# Prevents prompt-injection via system_prompt override (TC-E04).
_STRIP_FROM_CHAT = frozenset(["system_prompt", "system", "instructions"])


def _get_downstream_url(service: str, path: str) -> str:
    base = _SERVICE_MAP.get(service)
    if not base:
        raise HTTPException(status_code=404, detail=f"Unknown service: {service}")
    return f"{base}/api/v1/{service}{path}"


def _sanitize_chat_body(body: bytes, content_type: str) -> bytes:
    """
    Strip attacker-controlled system-prompt fields from chat request bodies.
    Only operates on JSON bodies sent to the chat service (TC-E04).
    """
    if "application/json" not in content_type or not body:
        return body
    try:
        parsed = _json.loads(body)
        if isinstance(parsed, dict):
            stripped = {k: v for k, v in parsed.items() if k not in _STRIP_FROM_CHAT}
            if len(stripped) != len(parsed):
                logger.warning(
                    "proxy_stripped_forbidden_fields",
                    fields=[k for k in parsed if k in _STRIP_FROM_CHAT],
                )
                return _json.dumps(stripped).encode()
    except Exception:
        pass
    return body


async def _proxy_request(request: Request, url: str, service: str = "") -> Response:
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

    # Strip forbidden fields from chat/stream requests (TC-E04)
    if service == "chat":
        body = _sanitize_chat_body(body, headers["Content-Type"])

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
    return await _proxy_request(request, url, service=service)
