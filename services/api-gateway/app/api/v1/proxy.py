from __future__ import annotations

import json as _json
import re
import httpx
import stripe
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.services.billing_service import create_agent_checkout_session

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
    """Raise 402 if tenant is not subscribed, or is at/above purchased agent slots.
    
    B1 FIX: Uses a Redis distributed lock to prevent TOCTOU races where two
    simultaneous agents can both pass the limit check before either increments
    the usage counter.
    """
    from app.services.tenant_service import get_plan_limits
    from app.services.auth_service import auth_service as _auth_service
    tenant, usage = await _get_tenant_and_usage(tenant_id, db)
    if tenant is None or usage is None:
        return

    # Gate 1: tenant has no paid subscription or 0 slots
    if tenant.subscription_status != "active" or usage.agent_count == 0:
        payment_url = None
        try:
            # Generate a checkout session for the user to purchase their first agent slot
            sub_resp = await _auth_service.create_subscription(
                tenant.email or "", tenant.plan or "voice_growth", db, None
            )
            payment_url = sub_resp.payment_url
        except Exception as e:
            logger.warning("agent_create_payment_url_failed", error=str(e))

        raise HTTPException(
            status_code=402,
            detail={
                "message": "A paid subscription is required to deploy an AI agent.",
                "payment_url": payment_url,
            },
        )

    # Gate 2: Check if they are at their agent limit
    purchased_slots = usage.agent_count

    # Query actual agent count from orchestrator
    actual_count = 0
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{settings.AI_ORCHESTRATOR_URL}/api/v1/agents",
                headers={"X-Tenant-ID": tenant_id, "X-Internal-Key": settings.INTERNAL_API_KEY}
            )
            if resp.status_code == 200:
                agents = resp.json()
                actual_count = len(agents)
    except Exception as e:
        logger.warning("agent_count_query_error", error=str(e))
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
    limits = await get_plan_limits(tenant.plan or "professional", db)
    current = usage.current_month_messages if usage else 0
    if not check_limit(limits.get("max_messages_per_month", 0), current):
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
    """Increment current_month_messages on TenantUsage.
    
    B9 FIX: Chat unit accounting has been removed from here. The orchestrator
    (session_billing_service.py::update_analytics) is the single source of truth
    for chat units to prevent double-counting. This function only increments
    the raw message counter and session counter.
    """
    from app.models.tenant import TenantUsage
    import uuid as _uuid
    tid = _uuid.UUID(tenant_id)
    usage_res = await db.execute(select(TenantUsage).where(TenantUsage.tenant_id == tid))
    usage = usage_res.scalar_one_or_none()
    if usage:
        usage.current_month_messages = (usage.current_month_messages or 0) + 1
        # Sessions: increment on the first turn
        if turn_count == 1:
            usage.current_month_sessions = (usage.current_month_sessions or 0) + 1
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
    "playbooks": settings.AI_ORCHESTRATOR_URL,
    "guardrails": settings.AI_ORCHESTRATOR_URL,
    "tools": settings.MCP_SERVER_URL,
    "context": settings.MCP_SERVER_URL,
    "voice": settings.VOICE_PIPELINE_URL,
}

_TIMEOUT = httpx.Timeout(settings.PROXY_TIMEOUT_SECONDS, connect=settings.PROXY_CONNECT_TIMEOUT_SECONDS)

# Fields that clients must never be allowed to inject into downstream requests.
# Prevents prompt-injection via system_prompt override (TC-E04).
_STRIP_FROM_CHAT = frozenset(["system_prompt", "system", "instructions"])


# Services that are mounted under /agents in the AI Orchestrator
_AGENT_BASED_SERVICES = frozenset(["playbooks", "guardrails"])

def _get_downstream_url(service: str, path: str) -> str:
    # Map playbooks and guardrails to agents service (they're mounted under /agents in orchestrator)
    downstream_service = "agents" if service in _AGENT_BASED_SERVICES else service
    base = _SERVICE_MAP.get(downstream_service)
    if not base:
        raise HTTPException(status_code=404, detail=f"Unknown service: {service}")
    path = path.lstrip("/")
    if path:
        return f"{base}/api/v1/{downstream_service}/{path}"
    else:
        return f"{base}/api/v1/{downstream_service}"


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
    # Attach shared internal secret so the ai-orchestrator can verify this
    # request originated from the trusted api-gateway (CRIT-002 defense).
    if settings.INTERNAL_API_KEY:
        headers["X-Internal-Key"] = settings.INTERNAL_API_KEY
    # Propagate W3C traceparent so downstream services continue the same trace
    if _trace_id and _span_id:
        headers["traceparent"] = f"00-{_trace_id}-{_span_id}-01"

    body = await request.body()

    if len(body) > settings.MAX_BODY_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Request body too large (max {settings.MAX_BODY_BYTES // (1024 * 1024)} MB).",
        )

    # Strip forbidden fields from chat/stream requests (TC-E04)
    if service == "chat":
        body = _sanitize_chat_body(body, headers["Content-Type"])

    try:
        if "/stream" in url:
            # Streaming path - create client inside generator to avoid premature closure
            async def stream_generator():
                _turn_count = 0
                async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
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
                                _text = chunk.decode("utf-8", errors="ignore")
                                if '"turn_count":' in _text:
                                    import re as _re
                                    _m = _re.search(r'"turn_count":\s*(\d+)', _text)
                                    if _m:
                                        _turn_count = int(_m.group(1))
                            except Exception:
                                pass
            
            media = "audio/mpeg" if "/tts/" in url or service == "voice" else "text/event-stream"
            return StreamingResponse(stream_generator(), media_type=media)

        # Non-streaming path
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
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
                    pass

            if resp.status_code >= 400:
                logger.warning(
                    "proxy_downstream_error",
                    service=service,
                    status_code=resp.status_code,
                    path=path,
                )
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
    if not tenant_id and request.url.path not in PUBLIC_PATHS:
        logger.warning("proxy_auth_failed_no_tenant", path=request.url.path)
        raise HTTPException(status_code=401, detail="Authentication required for proxy requests.")
    
    method = request.method.upper()
    full_path = f"{service}/{path}".strip("/")

    # ── Pre-request plan limit checks ────────────────────────────────────────
    if tenant_id and service == "agents":
        if method == "POST" and _CHAT_SEND.match(full_path):
            await _check_message_limit(tenant_id, db)

    # ── Forward the request ───────────────────────────────────────────────────
    url = _get_downstream_url(service, f"/{path}" if path else "")

    # CUSTOM HANDLING: Agent Creation (Draft-First Flow)
    if service == "agents" and method == "POST" and _AGENT_CREATE.match(full_path):
        import asyncio as _asyncio

        # ── B1 FIX: Distributed lock prevents TOCTOU race where two concurrent
        # requests both pass the slot check before either one has created an agent.
        _redis = getattr(request.app.state, "redis", None)
        _lock_key = f"agent_create_lock:{tenant_id}"
        _lock_acquired = False

        if _redis:
            try:
                # SET NX with 15s TTL — agent create should complete well within that
                _lock_acquired = await _redis.set(_lock_key, "1", nx=True, ex=15)
                if not _lock_acquired:
                    raise HTTPException(
                        status_code=429,
                        detail="Another agent creation is already in progress. Please wait a moment and try again.",
                    )
            except HTTPException:
                raise
            except Exception as _lock_err:
                # Redis unavailable — log but allow request to proceed (fail open)
                logger.warning("agent_create_lock_redis_error", error=str(_lock_err), tenant_id=tenant_id)
                _lock_acquired = False

        try:
            tenant, usage = await _get_tenant_and_usage(tenant_id, db)

            purchased_slots = usage.agent_count if usage else 0
            actual_count = 0
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    res = await client.get(f"{settings.AI_ORCHESTRATOR_URL}/api/v1/agents", headers={"X-Tenant-ID": tenant_id, "X-Internal-Key": settings.INTERNAL_API_KEY})
                    if res.status_code == 200:
                        actual_count = len(res.json())
            except Exception:
                pass

            has_slot = False
            if tenant and tenant.subscription_status == "active" and (actual_count < purchased_slots):
                has_slot = True

            try:
                body_dict = await request.json()
            except Exception:
                body_dict = {}
                
            body_dict["is_active"] = has_slot
            
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                headers = {
                    "X-Tenant-ID": tenant_id,
                    "X-User-ID": getattr(request.state, "user_id", ""),
                    "X-Role": getattr(request.state, "role", ""),
                    "X-Internal-Key": settings.INTERNAL_API_KEY,
                    "Content-Type": "application/json",
                }
                resp = await client.post(url, json=body_dict, headers=headers)
                
                if resp.status_code == 201:
                    if has_slot:
                        return Response(content=resp.content, status_code=201)
                    
                    # Create draft and redirect to Stripe
                    agent_data = resp.json()
                    agent_id = agent_data.get("id")
                    try:
                        requested_plan = body_dict.get("plan")
                        _origin = request.headers.get("Origin") or request.headers.get("Referer", "").split("/api")[0]
                        _frontend_url = _origin.rstrip("/") if _origin else None
                        payment_url = await create_agent_checkout_session(tenant_id, agent_id, db, requested_plan=requested_plan, frontend_url=_frontend_url)
                        raise HTTPException(
                            status_code=402,
                            detail={
                                "message": "AI Agent drafted successfully. Payment required for activation.",
                                "agent_id": agent_id,
                                "payment_url": payment_url,
                            }
                        )
                    except HTTPException:
                        raise
                    except Exception as e:
                        logger.error("agent_payment_url_failed", error=str(e), agent_id=agent_id)
                        return Response(content=resp.content, status_code=201)

                return Response(content=resp.content, status_code=resp.status_code)

        finally:
            # B1 FIX: Always release the distributed create-lock so the next
            # create request from this tenant is not permanently blocked.
            if _redis and _lock_acquired:
                try:
                    await _redis.delete(_lock_key)
                except Exception as _unlock_err:
                    logger.warning("agent_create_lock_release_error", error=str(_unlock_err), tenant_id=tenant_id)


    # CUSTOM HANDLING: Agent Deletion — auto-cancel Stripe subscription
    if service == "agents" and method == "DELETE" and _AGENT_DELETE.match(full_path):
        import asyncio as _asyncio
        stripe.api_key = settings.STRIPE_SECRET_KEY
        sub_id = None
        async with httpx.AsyncClient(timeout=5.0) as client:
            agent_resp = await client.get(url, headers={"X-Tenant-ID": tenant_id, "X-Internal-Key": settings.INTERNAL_API_KEY})
            if agent_resp.status_code == 200:
                agent_info = agent_resp.json()
                sub_id = agent_info.get("stripe_subscription_id")
                if sub_id:
                    try:
                        # B3 FIX: Run blocking Stripe SDK call in a thread so we don't block the event loop
                        subscription = await _asyncio.to_thread(stripe.Subscription.retrieve, sub_id)
                        if subscription.status in ("active", "trialing", "past_due"):
                            # Auto-cancel immediately — user is explicitly deleting the agent
                            await _asyncio.to_thread(stripe.Subscription.delete, sub_id)
                            logger.info(
                                "agent_subscription_cancelled_on_delete",
                                agent_id=agent_info.get("id"),
                                subscription_id=sub_id,
                                tenant_id=tenant_id,
                            )
                    except stripe.error.StripeError as e:
                        logger.error(
                            "agent_subscription_cancel_failed",
                            subscription_id=sub_id,
                            error=str(e),
                        )
                        raise HTTPException(
                            status_code=502,
                            detail="Could not cancel the billing subscription for this agent. "
                                   "Please try again or contact support.",
                        )

        # B3 FIX: Only proxy the delete and decrement slot count if orchestrator responds with success.
        # Previously, decrement ran even if the orchestrator returned an error.
        delete_resp = await _proxy_request(request, url, path, db, service=service)
        if hasattr(delete_resp, 'status_code') and delete_resp.status_code in (200, 204):
            if sub_id:
                try:
                    await _increment_agent_count(tenant_id, -1, db)
                except Exception as e:
                    logger.warning("agent_count_decrement_failed", error=str(e), tenant_id=tenant_id)
        else:
            logger.warning(
                "agent_delete_orchestrator_failed_slot_not_decremented",
                tenant_id=tenant_id,
                status_code=getattr(delete_resp, 'status_code', 'unknown'),
            )
        return delete_resp

    return await _proxy_request(request, url, path, db, service=service)
