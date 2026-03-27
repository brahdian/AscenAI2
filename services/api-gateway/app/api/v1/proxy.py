from __future__ import annotations

import json as _json
import re

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/proxy")

# ── Plan enforcement helpers ──────────────────────────────────────────────────

async def _get_tenant_and_usage(tenant_id: str, db: AsyncSession):
    """Load Tenant + TenantUsage in a single round-trip."""
    from app.models.tenant import Tenant, TenantUsage
    t_res = await db.execute(select(Tenant).where(Tenant.id == __import__("uuid").UUID(tenant_id)))
    u_res = await db.execute(select(TenantUsage).where(TenantUsage.tenant_id == __import__("uuid").UUID(tenant_id)))
    return t_res.scalar_one_or_none(), u_res.scalar_one_or_none()


async def _check_agent_limit(tenant_id: str, db: AsyncSession) -> None:
    """Raise 429 if tenant is at or above max_agents for their plan."""
    from app.services.tenant_service import get_plan_limits, check_limit
    tenant, usage = await _get_tenant_and_usage(tenant_id, db)
    if tenant is None:
        return
    limits = get_plan_limits(tenant.plan or "professional")
    current = usage.agent_count if usage else 0
    if not check_limit(limits["max_agents"], current):
        raise HTTPException(
            status_code=429,
            detail=f"Plan limit reached: your {tenant.plan} plan allows up to "
                   f"{limits['max_agents']} agent(s). Upgrade to add more.",
        )


async def _check_message_limit(tenant_id: str, db: AsyncSession) -> None:
    """Raise 429 if tenant has exhausted their monthly message quota."""
    from app.services.tenant_service import get_plan_limits, check_limit
    tenant, usage = await _get_tenant_and_usage(tenant_id, db)
    if tenant is None:
        return
    limits = get_plan_limits(tenant.plan or "professional")
    current = usage.current_month_messages if usage else 0
    if not check_limit(limits["max_messages_per_month"], current):
        raise HTTPException(
            status_code=429,
            detail=f"Monthly message limit reached ({limits['max_messages_per_month']} messages "
                   f"on the {tenant.plan} plan). Upgrade or wait until next billing cycle.",
        )


async def _increment_agent_count(tenant_id: str, delta: int, db: AsyncSession) -> None:
    """Increment or decrement the agent_count on TenantUsage."""
    from app.models.tenant import TenantUsage
    import uuid as _uuid
    tid = _uuid.UUID(tenant_id)
    usage_res = await db.execute(select(TenantUsage).where(TenantUsage.tenant_id == tid))
    usage = usage_res.scalar_one_or_none()
    if usage:
        usage.agent_count = max(0, (usage.agent_count or 0) + delta)
        await db.commit()


async def _increment_message_count(tenant_id: str, db: AsyncSession) -> None:
    """Increment current_month_messages on TenantUsage."""
    from app.models.tenant import TenantUsage
    import uuid as _uuid
    tid = _uuid.UUID(tenant_id)
    usage_res = await db.execute(select(TenantUsage).where(TenantUsage.tenant_id == tid))
    usage = usage_res.scalar_one_or_none()
    if usage:
        usage.current_month_messages = (usage.current_month_messages or 0) + 1
        await db.commit()


# Regex patterns for routes that need plan enforcement
_AGENT_CREATE = re.compile(r"^agents/?$")                     # POST /proxy/agents
_AGENT_DELETE = re.compile(r"^agents/[^/]+/?$")               # DELETE /proxy/agents/{id}
_CHAT_SEND    = re.compile(r"^agents/[^/]+/chat/?$")          # POST /proxy/agents/{id}/chat

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
async def proxy(
    service: str,
    path: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Generic reverse proxy with plan-limit enforcement and usage tracking."""
    tenant_id: str = getattr(request.state, "tenant_id", "") or ""
    method = request.method.upper()

    # ── Pre-request plan limit checks ────────────────────────────────────────
    if tenant_id and service == "agents":
        if method == "POST" and _AGENT_CREATE.match(path.lstrip("/")):
            await _check_agent_limit(tenant_id, db)
        elif method == "POST" and _CHAT_SEND.match(path.lstrip("/")):
            await _check_message_limit(tenant_id, db)

    # ── Forward the request ───────────────────────────────────────────────────
    url = _get_downstream_url(service, f"/{path}" if path else "")
    resp = await _proxy_request(request, url, service=service)

    # ── Post-request usage tracking ───────────────────────────────────────────
    if tenant_id and service == "agents" and resp.status_code < 300:
        if method == "POST" and _AGENT_CREATE.match(path.lstrip("/")):
            await _increment_agent_count(tenant_id, +1, db)
        elif method == "DELETE" and _AGENT_DELETE.match(path.lstrip("/")):
            await _increment_agent_count(tenant_id, -1, db)
        elif method == "POST" and _CHAT_SEND.match(path.lstrip("/")):
            await _increment_message_count(tenant_id, db)

    return resp
