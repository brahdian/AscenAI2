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
    import uuid as _uuid
    tid = _uuid.UUID(tenant_id)
    t_res = await db.execute(select(Tenant).where(Tenant.id == tid))
    u_res = await db.execute(select(TenantUsage).where(TenantUsage.tenant_id == tid))
    return t_res.scalar_one_or_none(), u_res.scalar_one_or_none()


async def _check_agent_limit(tenant_id: str, db: AsyncSession) -> None:
    """Raise 402 if tenant is at or above purchased agent slots."""
    from app.services.tenant_service import get_plan_limits
    tenant, usage = await _get_tenant_and_usage(tenant_id, db)
    if tenant is None or usage is None:
        return
    
    purchased_slots = usage.agent_count
    
    # Query actual agent count from orchestrator
    actual_count = 0
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{settings.AI_ORCHESTRATOR_URL}/api/v1/agents",
                headers={"X-Tenant-ID": tenant_id}
            )
            if resp.status_code == 200:
                agents = resp.json()
                actual_count = len(agents)
    except Exception as e:
        logger.warning("agent_count_query_error", error=str(e))
        # If we can't check, we might want to fail safe or allow?
        # Given the "upfront payment" requirement, we should probably be strict.
        pass

    if actual_count >= purchased_slots:
        raise HTTPException(
            status_code=402,
            detail=f"No available agent slots. You have {actual_count} agent(s) and {purchased_slots} slot(s). "
                   f"Please purchase an additional slot in the Billing section."
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


async def _increment_message_count(tenant_id: str, db: AsyncSession, turn_count: int = 0) -> None:
    """Increment current_month_messages and optionally chat units on TenantUsage."""
    from app.models.tenant import TenantUsage
    import uuid as _uuid
    tid = _uuid.UUID(tenant_id)
    usage_res = await db.execute(select(TenantUsage).where(TenantUsage.tenant_id == tid))
    usage = usage_res.scalar_one_or_none()
    if usage:
        usage.current_month_messages = (usage.current_month_messages or 0) + 1
        # Chat units: 1 unit per 10 turns. The first turn (turn_count=1) increments it.
        # subsequent increments at turn 11, 21, etc.
        if turn_count > 0 and (turn_count % 10 == 1):
            usage.current_month_chat_units = (usage.current_month_chat_units or 0) + 1
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
    "templates": settings.AI_ORCHESTRATOR_URL,
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
    path = path.lstrip("/")
    if path:
        return f"{base}/api/v1/{service}/{path}"
    else:
        return f"{base}/api/v1/{service}"


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


async def _proxy_request(
    request: Request,
    url: str,
    path: str,
    db: AsyncSession,
    service: str = "",
):
    """Forward a request to a downstream service and return the response."""
    # Forward auth headers plus tenant context
    _trace_id = getattr(request.state, "trace_id", "")
    _span_id = getattr(request.state, "span_id", "")
    headers = {
        "X-Tenant-ID": getattr(request.state, "tenant_id", ""),
        "X-User-ID": getattr(request.state, "user_id", ""),
        "X-Role": getattr(request.state, "role", ""),
        "X-Trace-ID": _trace_id,
        "Content-Type": request.headers.get("Content-Type", "application/json"),
    }
    # Propagate W3C traceparent so downstream services continue the same trace
    if _trace_id and _span_id:
        headers["traceparent"] = f"00-{_trace_id}-{_span_id}-01"

    body = await request.body()

    _MAX_BODY_BYTES = 10 * 1024 * 1024  # 10 MB
    if len(body) > _MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Request body too large (max 10 MB).")

    # Strip forbidden fields from chat/stream requests (TC-E04)
    if service == "chat":
        body = _sanitize_chat_body(body, headers["Content-Type"])

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            if "/stream" in url:
                # Streaming path
                async def stream_generator():
                    _turn_count = 0
                    async with client.stream(
                        method=request.method,
                        url=url,
                        headers=headers,
                        content=body,
                        params=dict(request.query_params),
                    ) as resp:
                        async for chunk in resp.aiter_bytes():
                            yield chunk
                            try:
                                # Safe extraction from the 'done' event payload
                                _text = chunk.decode("utf-8", errors="ignore")
                                if '"turn_count":' in _text:
                                    import re as _re
                                    _m = _re.search(r'"turn_count":\s*(\d+)', _text)
                                    if _m:
                                        _turn_count = int(_m.group(1))
                            except Exception:
                                pass
                    
                    # Intercept billing increment after stream ends
                    full_path = f"{service}/{path}".strip("/")
                    if service == "agents" and request.method == "POST" and _CHAT_SEND.match(full_path):
                        await _increment_message_count(getattr(request.state, "tenant_id", ""), db, turn_count=_turn_count)

                media = "audio/mpeg" if "/tts/" in url or service == "voice" else "text/event-stream"
                return StreamingResponse(stream_generator(), media_type=media)

            resp = await client.request(
                method=request.method,
                url=url,
                headers=headers,
                content=body,
                params=dict(request.query_params),
            )
            
            # Post-request hooks for Non-streaming responses
            if resp.status_code < 300:
                tenant_id = getattr(request.state, "tenant_id", "")
                if service == "agents":
                    full_path = f"{service}/{path}".strip("/")
                    # We NO LONGER auto-increment/decrement agent_count here.
                    # agent_count now represents "Purchased Slots" managed by billing.
                    if request.method == "POST" and _CHAT_SEND.match(full_path):
                        _turn_count = 0
                        if resp.headers.get("Content-Type") == "application/json":
                            try:
                                _payload = _json.loads(resp.content)
                                _turn_count = _payload.get("turn_count", 0)
                            except Exception:
                                pass
                        await _increment_message_count(tenant_id, db, turn_count=_turn_count)

            return Response(
                content=resp.content,
                status_code=resp.status_code,
                headers={
                    k: v
                    for k, v in resp.headers.items()
                    if k.lower() not in ("content-encoding", "transfer-encoding", "connection")
                },
            )
    except httpx.ConnectError as exc:
        logger.error("proxy_connect_error", url=url, error=str(exc))
        raise HTTPException(status_code=503, detail="Downstream service unavailable.")
    except httpx.TimeoutException as exc:
        logger.error("proxy_timeout", url=url, error=str(exc))
        raise HTTPException(status_code=504, detail="Downstream service timed out.")


@router.api_route(
    "/{service}/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    response_model=None,
)
async def proxy(
    service: str,
    path: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Generic reverse proxy with plan-limit enforcement and usage tracking."""
    tenant_id: str = getattr(request.state, "tenant_id", "") or ""
    method = request.method.upper()
    full_path = f"{service}/{path}".strip("/")

    # ── Pre-request plan limit checks ────────────────────────────────────────
    if tenant_id and service == "agents":
        if method == "POST" and _AGENT_CREATE.match(full_path):
            await _check_agent_limit(tenant_id, db)
        elif method == "POST" and _CHAT_SEND.match(full_path):
            await _check_message_limit(tenant_id, db)

    # ── Forward the request ───────────────────────────────────────────────────
    url = _get_downstream_url(service, f"/{path}" if path else "")
    return await _proxy_request(request, url, path, db, service=service)
