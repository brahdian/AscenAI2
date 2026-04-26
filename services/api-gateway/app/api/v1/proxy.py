from __future__ import annotations

import json as _json
import re
import uuid

import httpx
import stripe
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import generate_internal_token, get_current_tenant, get_tenant_db
from app.services.billing_service import create_agent_checkout_session

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/proxy")

# ── Plan enforcement helpers ──────────────────────────────────────────────────

async def _get_tenant_and_usage(tenant_id: str, db: AsyncSession):
    """Load Tenant + TenantUsage in a single round-trip."""
    import uuid as _uuid

    from app.models.tenant import Tenant, TenantUsage
    tid = _uuid.UUID(tenant_id)
    t_res = await db.execute(select(Tenant).where(Tenant.id == tid))
    u_res = await db.execute(select(TenantUsage).where(TenantUsage.tenant_id == tid))
    return t_res.scalar_one_or_none(), u_res.scalar_one_or_none()


async def _check_agent_limit(tenant_id: str, db: AsyncSession) -> None:
    """Raise 402 if tenant is not subscribed, or 409 if at/above purchased agent slots.

    Returns the list of active agents alongside each error so the frontend can
    render a meaningful Swap dialog rather than a bare error string.
    """
    from app.services.auth_service import auth_service as _auth_service
    tenant, usage = await _get_tenant_and_usage(tenant_id, db)
    if tenant is None or usage is None:
        return

    # Gate 1: tenant has no paid subscription or 0 slots
    if tenant.subscription_status != "active" or usage.agent_count == 0:
        payment_url = None
        try:
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

    # Gate 2: Check active agent count against purchased slots.
    # Only ACTIVE agents consume a slot — archived/draft/pending do not.
    purchased_slots = usage.agent_count
    active_agents = []
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{settings.AI_ORCHESTRATOR_URL}/api/v1/agents",
                params={"status": "active"},
                headers={"X-Tenant-ID": tenant_id, "X-Internal-Key": settings.INTERNAL_API_KEY},
            )
            if resp.status_code == 200:
                active_agents = resp.json()
    except Exception as e:
        logger.warning("agent_count_query_error", error=str(e))

    if len(active_agents) >= purchased_slots:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "at_slot_capacity",
                "message": (
                    f"All {purchased_slots} slot(s) are in use. "
                    "Archive an active agent to free a slot, or purchase additional slots."
                ),
                "slots_used": len(active_agents),
                "slots_total": purchased_slots,
                "active_agents": [
                    {"id": a.get("id"), "name": a.get("name")}
                    for a in active_agents
                ],
            },
        )


async def _check_message_limit(tenant_id: str, db: AsyncSession) -> None:
    """Raise 429 if tenant has exhausted their monthly message quota."""
    from app.services.tenant_service import check_limit, get_plan_limits
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
    import uuid as _uuid

    from app.models.tenant import TenantUsage
    tid = _uuid.UUID(tenant_id)
    usage_res = await db.execute(select(TenantUsage).where(TenantUsage.tenant_id == tid))
    usage = usage_res.scalar_one_or_none()
    if usage:
        usage.agent_count = max(0, (usage.agent_count or 0) + delta)
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
    "escalation": settings.AI_ORCHESTRATOR_URL,
    "workflows": settings.AI_ORCHESTRATOR_URL,
    "platform": settings.AI_ORCHESTRATOR_URL,
    "tools": settings.MCP_SERVER_URL,
    "context": settings.MCP_SERVER_URL,
    "voice": settings.VOICE_PIPELINE_URL,
}

_TIMEOUT = httpx.Timeout(settings.PROXY_TIMEOUT_SECONDS, connect=settings.PROXY_CONNECT_TIMEOUT_SECONDS)

# Fields that clients must never be allowed to inject into downstream requests.
# Prevents prompt-injection via system_prompt override (TC-E04).
_STRIP_FROM_CHAT = frozenset(["system_prompt", "system", "instructions"])


# Services that are mounted under /agents in the AI Orchestrator
_AGENT_BASED_SERVICES = frozenset(["playbooks", "guardrails", "workflows", "learning", "documents", "evals", "prompts", "variables"])

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
        "X-Actor-Email": getattr(request.state, "actor_email", ""),
        "X-Role": getattr(request.state, "role", ""),
        "X-Trace-ID": _trace_id,
        "X-Is-Support-Access": "true" if getattr(request.state, "is_support_access", False) else "false",
        "X-Original-IP": getattr(request.state, "client_ip", "unknown"),
        "Content-Type": request.headers.get("Content-Type", "application/json"),
    }

    # Signal restricted agent-lockout to downstream services (CRIT-005 deep defense)
    api_agent_id = getattr(request.state, "api_key_agent_id", None)
    if api_agent_id:
        headers["X-Restricted-Agent-ID"] = str(api_agent_id)

    # Attach shared internal secret and signed JWT for inter-service authentication (CRIT-002 defense).
    if settings.INTERNAL_API_KEY:
        headers["X-Internal-Key"] = settings.INTERNAL_API_KEY
    headers["Authorization"] = f"Bearer {generate_internal_token()}"
    # Propagate W3C traceparent so downstream services continue the same trace
    if _trace_id and _span_id:
        headers["traceparent"] = f"00-{_trace_id}-{_span_id}-01"

    # Use cached body if available (CRIT-005 Fix: prevent double consumption)
    body = getattr(request.state, "body_bytes", None)
    if body is None:
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
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
):
    """Generic reverse proxy with plan-limit enforcement and usage tracking."""
    # Auth is already enforced by the get_tenant_db dependency (TC-A01)
    
    method = request.method.upper()
    full_path = f"{service}/{path}".strip("/")

    # ── Pre-request plan limit checks ────────────────────────────────────────
    if tenant_id and service == "agents":
        if method == "POST" and _CHAT_SEND.match(full_path):
            await _check_message_limit(tenant_id, db)

    # ── RBAC & Scope Enforcement (CRIT-001 Fix) ───────────────────────────────
    # For API Key authentication, we MUST validate that the key has the required
    # scope for the requested service/action.
    auth_method = getattr(request.state, "auth_method", "jwt")
    if auth_method == "api_key":
        api_scopes = getattr(request.state, "api_key_scopes", []) or []
        
        # 1. 'admin' scope bypasses all granular checks
        if "admin" not in api_scopes:
            # 2. DELETE/PATCH/PUT are restricted to 'admin' or specific 'write' scopes
            if method in ("DELETE", "PATCH", "PUT"):
                required_write = f"{service}:write"
                if required_write not in api_scopes:
                    raise HTTPException(
                        status_code=403,
                        detail=f"API Key missing required write scope: {required_write} (or 'admin')"
                    )

            # 3. Chat and Session management for widgets
            if service in ("chat", "sessions", "feedback"):
                if "chat" not in api_scopes:
                    raise HTTPException(
                        status_code=403,
                        detail="API Key missing 'chat' scope required for widget interactions."
                    )
            
            # 5. Agent-level Scoping (CRIT-005 Fix)
            # If the API key is restricted to a specific Agent, enforce that here.
            api_agent_id = getattr(request.state, "api_key_agent_id", None)
            if api_agent_id:
                # Cache the body bytes so we can inspect it here AND forward it later
                # without exhausting the request stream (CRIT-FIX).
                body_bytes = b""
                if method in ("POST", "PUT", "PATCH"):
                    body_bytes = await request.body()
                    request.state.body_bytes = body_bytes

                # Case A: Service is 'agents' (ID is usually in the URL path)
                if service == "agents":
                    path_parts = path.strip("/").split("/")
                    if path_parts:
                        target_id = path_parts[0]
                        if target_id and len(target_id) > 30: # Basic UUID length check
                            if target_id != api_agent_id:
                                logger.warning("auth_api_key_agent_mismatch", key_agent_id=api_agent_id, requested_agent_id=target_id)
                                raise HTTPException(status_code=403, detail=f"API Key restricted to Agent {api_agent_id}.")
                        elif not target_id or target_id == "":
                            raise HTTPException(status_code=403, detail="API Key restricted to a single agent. Listing all agents is blocked.")

                # Case B: Service is 'chat' (Agent ID is in JSON body)
                elif service == "chat" and body_bytes:
                    try:
                        body_json = _json.loads(body_bytes)
                        target_id = body_json.get("agent_id")
                        if target_id and target_id != api_agent_id:
                            logger.warning("auth_api_key_chat_agent_mismatch", key_agent_id=api_agent_id, requested_agent_id=target_id)
                            raise HTTPException(status_code=403, detail=f"API Key restricted to Agent {api_agent_id}.")
                    except _json.JSONDecodeError: pass

                # Case C: Other services (sessions, feedback)
                elif service in ("sessions", "feedback") and body_bytes:
                    try:
                        body_json = _json.loads(body_bytes)
                        target_id = body_json.get("agent_id")
                        if target_id and target_id != api_agent_id:
                            raise HTTPException(status_code=403, detail=f"API Key restricted to Agent {api_agent_id}.")
                    except: pass


            # 6. Block all other services (analytics, billing, etc.) for non-admin keys
            elif service not in ("chat", "sessions", "feedback", "agents"):
                raise HTTPException(
                    status_code=403,
                    detail=f"API Key restricted. Scope required for service '{service}'."
                )

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
            # Only count ACTIVE agents against the slot quota
            active_agents_list = []
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    res = await client.get(
                        f"{settings.AI_ORCHESTRATOR_URL}/api/v1/agents",
                        params={"status": "active"},
                        headers={"X-Tenant-ID": tenant_id, "X-Internal-Key": settings.INTERNAL_API_KEY},
                    )
                    if res.status_code == 200:
                        active_agents_list = res.json()
            except Exception:
                pass

            active_count = len(active_agents_list)
            has_slot = bool(
                tenant
                and tenant.subscription_status == "active"
                and active_count < purchased_slots
            )

            try:
                body_dict = await request.json()
            except Exception:
                body_dict = {}

            # Extract template context for automatic instantiation
            template_ctx = body_dict.pop("template_context", None)
            if template_ctx:
                # B4 FIX: Inject into agent_config so it's persisted in the orchestrator
                # This ensures we can recover the template config after payment redirect.
                body_dict.setdefault("agent_config", {})["template_context"] = template_ctx
            
            logger.info("gateway_preparing_agent_create", tenant_id=tenant_id, template_id=template_ctx.get("template_id") if template_ctx else None)
                
            body_dict["is_active"] = has_slot
            if not has_slot:
                body_dict["status"] = "PENDING_PAYMENT"
            
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                headers = {
                    "X-Tenant-ID": tenant_id,
                    "X-User-ID": getattr(request.state, "user_id", ""),
                    "X-Role": getattr(request.state, "role", ""),
                    "Authorization": f"Bearer {generate_internal_token()}",
                    "Content-Type": "application/json",
                }
                resp = await client.post(url, json=body_dict, headers=headers)
                
                if resp.status_code == 201:
                    agent_data = resp.json()
                    agent_id = agent_data.get("id")

                    # AUTOMATIC INSTANTIATION: Trigger immediately after agent creation
                    if template_ctx and agent_id:
                        template_id = template_ctx.get("template_id")
                        if template_id:
                            instantiate_url = f"{settings.AI_ORCHESTRATOR_URL}/api/v1/templates/{template_id}/instantiate"
                            instantiate_payload = {
                                "agent_id": agent_id,
                                "template_version_id": template_ctx.get("template_version_id"),
                                "variable_values": template_ctx.get("variable_values", {}),
                                "tool_configs": template_ctx.get("tool_configs", {}),
                            }
                            try:
                                inst_resp = await client.post(instantiate_url, json=instantiate_payload, headers=headers)
                                if inst_resp.status_code != 200:
                                    logger.warning("gateway_auto_instantiation_failed", agent_id=agent_id, status_code=inst_resp.status_code, detail=inst_resp.text)
                                else:
                                    logger.info("gateway_auto_instantiation_success", agent_id=agent_id, template_id=template_id)
                            except Exception as inst_err:
                                logger.error("gateway_auto_instantiation_error", agent_id=agent_id, error=str(inst_err))

                    if has_slot:
                        # ── CRIT-005 Fix: Automatic Widget Key Generation ────────────────
                        # When a new agent is created, automatically generate a restricted
                        # API key scoped ONLY to 'chat' and locked to this agent.
                        try:
                            from app.services.auth_service import auth_service
                            # Identify the user creating the agent
                            user_id = getattr(request.state, "user_id", "")
                            if user_id:
                                _, widget_key = await auth_service.create_api_key(
                                    tenant_id=uuid.UUID(tenant_id),
                                    user_id=uuid.UUID(user_id),
                                    name=f"Widget Key: {body_dict.get('name', 'New Agent')}",
                                    scopes=["chat", "sessions", "feedback"],
                                    db=db,
                                    agent_id=uuid.UUID(agent_id),
                                )
                                logger.info("gateway_auto_widget_key_created", agent_id=agent_id, key_id=str(widget_key.id))
                        except Exception as key_err:
                            logger.error("gateway_auto_widget_key_failed", agent_id=agent_id, error=str(key_err))

                        return Response(content=resp.content, status_code=201)
                    
                    # Create draft and redirect to Stripe
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

    # CUSTOM HANDLING: slot-activate — revive an ARCHIVED/PENDING agent into an empty slot
    _AGENT_SLOT_ACTIVATE = re.compile(r"^agents/([^/]+)/slot-activate$")
    if service == "agents" and method == "POST" and _AGENT_SLOT_ACTIVATE.match(full_path):
        m = _AGENT_SLOT_ACTIVATE.match(full_path)
        target_agent_id = m.group(1)

        _redis = getattr(request.app.state, "redis", None)
        _lock_key = f"slot_lock:{tenant_id}"
        _lock_acquired = False
        if _redis:
            try:
                _lock_acquired = await _redis.set(_lock_key, "1", nx=True, ex=15)
                if not _lock_acquired:
                    raise HTTPException(status_code=429, detail="A slot update is already in progress.")
            except HTTPException:
                raise
            except Exception as e:
                logger.warning("slot_lock_redis_error", error=str(e), tenant_id=tenant_id)
                
        try:
            # Check capacity first
            tenant, usage = await _get_tenant_and_usage(tenant_id, db)
            purchased_slots = usage.agent_count if usage else 0
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    res = await client.get(
                        f"{settings.AI_ORCHESTRATOR_URL}/api/v1/agents",
                        params={"status": "active"},
                        headers={"X-Tenant-ID": tenant_id, "X-Internal-Key": settings.INTERNAL_API_KEY},
                    )
                    active_agents_list = res.json() if res.status_code == 200 else []
            except Exception:
                active_agents_list = []

            active_count = len(active_agents_list)
            if active_count >= purchased_slots:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "at_slot_capacity",
                        "message": (
                            f"All {purchased_slots} slot(s) are in use. "
                            "Archive an active agent first to free a slot."
                        ),
                        "slots_used": active_count,
                        "slots_total": purchased_slots,
                        "active_agents": [
                            {"id": a.get("id"), "name": a.get("name")}
                            for a in active_agents_list
                        ],
                    },
                )

            # Slot is available — forward to orchestrator activate endpoint
            try:
                body_bytes = await request.body()
                async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                    int_headers = {
                        "X-Tenant-ID": tenant_id,
                        "Authorization": f"Bearer {generate_internal_token()}",
                        "Content-Type": "application/json",
                    }
                    activate_resp = await client.post(
                        f"{settings.AI_ORCHESTRATOR_URL}/api/v1/agents/{target_agent_id}/activate",
                        content=body_bytes,
                        headers=int_headers,
                    )
                    
                    if activate_resp.status_code == 200:
                        # Proactively update Stripe Metadata
                        agent_data = activate_resp.json()
                        sub_id = agent_data.get("stripe_subscription_id")
                        if sub_id:
                            import asyncio as _asyncio
                            try:
                                await _asyncio.to_thread(
                                    stripe.Subscription.modify,
                                    sub_id,
                                    metadata={"agent_id": target_agent_id, "tenant_id": tenant_id}
                                )
                            except Exception as stripe_err:
                                logger.warning("stripe_metadata_update_failed", error=str(stripe_err))

                    return Response(
                        content=activate_resp.content,
                        status_code=activate_resp.status_code,
                        media_type="application/json",
                    )
            except Exception as e:
                logger.error("slot_activate_proxy_error", error=str(e))
                raise HTTPException(status_code=502, detail="Failed to activate agent.")
        finally:
            if _redis and _lock_acquired:
                try:
                    await _redis.delete(_lock_key)
                except Exception:
                    pass

    # CUSTOM HANDLING: slot-archive — archive an ACTIVE agent to free its slot
    _AGENT_SLOT_ARCHIVE = re.compile(r"^agents/([^/]+)/slot-archive$")
    if service == "agents" and method == "POST" and _AGENT_SLOT_ARCHIVE.match(full_path):
        m = _AGENT_SLOT_ARCHIVE.match(full_path)
        target_agent_id = m.group(1)
        try:
            body_bytes = await request.body()
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                int_headers = {
                    "X-Tenant-ID": tenant_id,
                    "Authorization": f"Bearer {generate_internal_token()}",
                    "Content-Type": "application/json",
                }
                archive_resp = await client.post(
                    f"{settings.AI_ORCHESTRATOR_URL}/api/v1/agents/{target_agent_id}/archive",
                    content=body_bytes,
                    headers=int_headers,
                )
                return Response(
                    content=archive_resp.content,
                    status_code=archive_resp.status_code,
                    media_type="application/json",
                )
        except Exception as e:
            logger.error("slot_archive_proxy_error", error=str(e))
            raise HTTPException(status_code=502, detail="Failed to archive agent.")

    # CUSTOM HANDLING: slot-swap — atomic archive and activate
    _AGENT_SLOT_SWAP = re.compile(r"^agents/slot-swap$")
    if service == "agents" and method == "POST" and _AGENT_SLOT_SWAP.match(full_path):
        try:
            body_dict = await request.json()
            archive_id = body_dict.get("archive_id")
            activate_id = body_dict.get("activate_id")
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body")
            
        if not archive_id or not activate_id:
            raise HTTPException(status_code=400, detail="Missing archive_id or activate_id")
            
        _redis = getattr(request.app.state, "redis", None)
        _lock_key = f"slot_lock:{tenant_id}"
        _lock_acquired = False
        if _redis:
            try:
                _lock_acquired = await _redis.set(_lock_key, "1", nx=True, ex=15)
                if not _lock_acquired:
                    raise HTTPException(status_code=429, detail="A slot update is already in progress.")
            except HTTPException:
                raise
            except Exception as e:
                logger.warning("slot_lock_redis_error", error=str(e), tenant_id=tenant_id)
                
        try:
            int_headers = {
                "X-Tenant-ID": tenant_id,
                "Authorization": f"Bearer {generate_internal_token()}",
                "Content-Type": "application/json",
            }
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                # 1. Archive
                archive_resp = await client.post(
                    f"{settings.AI_ORCHESTRATOR_URL}/api/v1/agents/{archive_id}/archive",
                    headers=int_headers,
                )
                if archive_resp.status_code not in (200, 204):
                    logger.error("slot_swap_archive_failed", archive_id=archive_id, status=archive_resp.status_code)
                    raise HTTPException(status_code=502, detail="Failed to archive agent during swap.")
                    
                # 2. Activate
                activate_resp = await client.post(
                    f"{settings.AI_ORCHESTRATOR_URL}/api/v1/agents/{activate_id}/activate",
                    headers=int_headers,
                )
                if activate_resp.status_code != 200:
                    logger.error("slot_swap_activate_failed", activate_id=activate_id, status=activate_resp.status_code)
                    raise HTTPException(status_code=502, detail="Failed to activate agent during swap.")
                
                # 3. Stripe Metadata Update
                agent_data = activate_resp.json()
                sub_id = agent_data.get("stripe_subscription_id")
                if sub_id:
                    import asyncio as _asyncio
                    try:
                        await _asyncio.to_thread(
                            stripe.Subscription.modify,
                            sub_id,
                            metadata={"agent_id": activate_id, "tenant_id": tenant_id}
                        )
                    except Exception as e:
                        logger.warning("stripe_metadata_update_failed", error=str(e))

                return Response(
                    content=activate_resp.content,
                    status_code=activate_resp.status_code,
                    media_type="application/json",
                )
        except HTTPException:
            raise
        except Exception as e:
            logger.error("slot_swap_proxy_error", error=str(e))
            raise HTTPException(status_code=502, detail="Failed to swap agents.")
        finally:
            if _redis and _lock_acquired:
                try:
                    await _redis.delete(_lock_key)
                except Exception:
                    pass

    return await _proxy_request(request, url, path, db, service=service)
