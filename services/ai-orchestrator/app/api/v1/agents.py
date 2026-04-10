from __future__ import annotations

import copy
import os
import re
import time
import uuid
import json
from datetime import datetime, timezone
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_tenant_db, get_current_tenant, require_forwarded_role
from app.models.agent import Agent, AgentPlaybook, AgentGuardrails
from app.schemas.chat import (
    AgentCreate,
    AgentResponse,
    AgentTestRequest,
    AgentUpdate,
    ChatResponse,
    ConnectorTestResult,
)
from app.services.agent_state_machine import AgentStateMachine
from app.guardrails.voice_agent_guardrails import (
    get_dynamic_voice_protocol,
    generate_multilingual_greeting,
    generate_multilingual_fallback,
)

logger = structlog.get_logger(__name__)
router = APIRouter()

# Patterns that indicate prompt injection attempts in stored system prompts
_PROMPT_INJECTION_RE = re.compile(
    r"(\[SYSTEM\]|\[INST\]|<system>|<\/system>|\[\/INST\]|<<SYS>>|<</SYS>>"
    r"|ignore (all |your )?(previous |prior )?instructions?"
    r"|you are now (in )?(developer|jailbreak|dan|unrestricted) mode"
    r"|disregard (your|all) (training|guidelines|rules|instructions)"
    r"|bypass (your|all) (safety|content|ethical) (filters?|guidelines?))",
    re.IGNORECASE,
)
_MAX_SYSTEM_PROMPT_LEN = 8_000


def _validate_system_prompt(prompt: str | None) -> None:
    if not prompt:
        return
    if len(prompt) > _MAX_SYSTEM_PROMPT_LEN:
        raise HTTPException(
            status_code=422,
            detail=f"system_prompt exceeds maximum length of {_MAX_SYSTEM_PROMPT_LEN} characters.",
        )
    if _PROMPT_INJECTION_RE.search(prompt):
        raise HTTPException(
            status_code=422,
            detail="system_prompt contains disallowed injection patterns.",
        )


def _tenant_id(request: Request) -> str:
    tid = request.headers.get("X-Tenant-ID") or getattr(request.state, "tenant_id", None)
    if not tid:
        raise HTTPException(status_code=401, detail="Tenant ID required.")
    return tid


async def _agent_to_response(agent: Agent, db: AsyncSession) -> AgentResponse:
    config = agent.agent_config or {}
    supported_langs = config.get("supported_languages", [])
    
    computed_greeting = await generate_multilingual_greeting(db, supported_langs)
    computed_protocol = await get_dynamic_voice_protocol(db, supported_langs)
    computed_fallback = await generate_multilingual_fallback(db, supported_langs)

    return AgentResponse(
        id=str(agent.id),
        tenant_id=str(agent.tenant_id),
        name=agent.name,
        description=agent.description,
        business_type=agent.business_type,
        personality=agent.personality,
        system_prompt=agent.system_prompt,
        agent_config=config,
        voice_enabled=agent.voice_enabled,
        voice_id=agent.voice_id,
        language=agent.language,
        auto_detect_language=config.get("auto_detect_language", False),
        supported_languages=supported_langs,
        greeting_message=config.get("greeting_message"),
        voice_greeting_url=config.get("voice_greeting_url"),
        voice_system_prompt=config.get("voice_system_prompt"),
        computed_greeting=computed_greeting,
        computed_protocol=computed_protocol,
        computed_fallback=computed_fallback,
        tools=config.get("tools", []),
        knowledge_base_ids=config.get("knowledge_base_ids", []),
        llm_config=config.get("llm_config", {}),
        escalation_config=config.get("escalation_config", {}),
        extension_number=agent.extension_number,
        is_available_as_tool=config.get("is_available_as_tool", True),
        is_active=agent.is_active,
        stripe_subscription_id=agent.stripe_subscription_id,
        deleted_at=agent.deleted_at.isoformat() if agent.deleted_at else None,
        created_at=agent.created_at.isoformat() if agent.created_at else None,
        updated_at=agent.updated_at.isoformat() if agent.updated_at else None,
    )


@router.get("/platform/global-guardrails")
async def get_platform_global_guardrails(
    db: AsyncSession = Depends(get_db),
):
    """Get global guardrails from DB/Redis cache."""
    from app.services.settings_service import SettingsService
    guardrails = await SettingsService.get_setting(db, "global_guardrails", default=[])
    return {"guardrails": guardrails}


@router.put("/platform/global-guardrails")
async def update_platform_global_guardrails(
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    """Update global guardrails (admin only). Writes to DB and updates Redis cache."""
    from app.services.settings_service import SettingsService
    guardrails = body.get("guardrails", [])

    await db.execute(
        text("INSERT INTO platform_settings (key, value) VALUES ('global_guardrails', :value) "
             "ON CONFLICT (key) DO UPDATE SET value = :value"),
        {"value": json.dumps(guardrails)}
    )
    await db.commit()

    await SettingsService.invalidate_cache("global_guardrails")
    logger.info("global_guardrails_updated", count=len(guardrails))
    return {"guardrails": guardrails}


@router.post("", response_model=AgentResponse, status_code=201)
async def create_agent(
    body: AgentCreate,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
):
    """Create a new AI agent for the tenant."""
    tenant_id = _tenant_id(request)
    _validate_system_prompt(body.system_prompt)

    agent_config = body.agent_config.copy() if body.agent_config else {}
    agent_config.setdefault("tone", body.personality or "professional")
    if body.system_prompt:
        agent_config.setdefault("instructions", body.system_prompt)
    agent_config.setdefault("greeting_message", f"Hi! I'm {body.name}. How can I help you today?")
    
    agent = Agent(
        id=uuid.uuid4(),
        tenant_id=uuid.UUID(tenant_id),
        name=body.name,
        description=body.description,
        business_type=body.business_type,
        personality=body.personality,
        system_prompt=body.system_prompt,
        voice_enabled=body.voice_enabled,
        voice_id=body.voice_id,
        language=body.language,
        extension_number=body.extension_number,
        is_available_as_tool=body.is_available_as_tool if body.is_available_as_tool is not None else True,
        is_active=body.is_active if body.is_active is not None else True,
        agent_config=agent_config,
    )
    db.add(agent)

    tenant_uuid = uuid.UUID(tenant_id)
    
    default_playbook = AgentPlaybook(
        id=uuid.uuid4(),
        agent_id=agent.id,
        tenant_id=tenant_uuid,
        name="Default",
        description="Default playbook — edit to add instructions for your agent.",
        is_default=True,
        intent_triggers=[],
        config={
            "instructions": body.system_prompt or "",
            "tone": body.personality or "professional",
            "dos": [],
            "donts": [],
            "scenarios": [],
        },
    )
    db.add(default_playbook)

    general_chat_playbook = AgentPlaybook(
        id=uuid.uuid4(),
        agent_id=agent.id,
        tenant_id=tenant_uuid,
        name="General Chat",
        description="Handle general conversations and questions not covered by other playbooks",
        is_active=True,
        intent_triggers=[],
        config={
            "instructions": body.system_prompt or "",
            "tone": body.personality or "professional",
            "dos": [],
            "donts": [],
            "scenarios": [],
        },
    )
    db.add(general_chat_playbook)

    default_guardrails = AgentGuardrails(
        id=uuid.uuid4(),
        agent_id=agent.id,
        tenant_id=tenant_uuid,
        config={
            "profanity_filter": True,
            "pii_redaction": False,
            "pii_pseudonymization": True,
            "is_active": True,
        },
        is_active=True,
    )
    db.add(default_guardrails)

    await db.commit()
    await db.refresh(agent)
    logger.info("agent_created", agent_id=str(agent.id), tenant_id=tenant_id)
    return await _agent_to_response(agent, db)


@router.get("", response_model=list[AgentResponse])
async def list_agents(
    status: str = "active",  # active, archived, all
    page: int = 1,
    limit: int = 50,
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
):
    """
    List agents for the tenant (paginated).
    - status=active (default): is_active=True
    - status=archived: is_active=False AND deleted_at IS NOT NULL
    - status=all: everything
    """
    page = max(1, page)
    limit = min(max(1, limit), 200)
    offset = (page - 1) * limit

    query = select(Agent).where(Agent.tenant_id == uuid.UUID(tenant_id))

    if status == "active":
        query = query.where(Agent.is_active.is_(True))
    elif status == "archived":
        query = query.where(Agent.is_active.is_(False), Agent.deleted_at.is_not(None))

    result = await db.execute(
        query.order_by(Agent.created_at.desc()).limit(limit).offset(offset)
    )
    agents = result.scalars().all()
    return [await _agent_to_response(a, db) for a in agents]


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: str,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
):
    """Get a specific agent by ID."""
    tenant_id = _tenant_id(request)
    result = await db.execute(
        select(Agent).where(
            Agent.id == uuid.UUID(agent_id),
            Agent.tenant_id == uuid.UUID(tenant_id),
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found.")
    return await _agent_to_response(agent, db)


@router.patch("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: str,
    body: AgentUpdate,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
):
    """Update an agent's configuration."""
    tenant_id = _tenant_id(request)
    if body.system_prompt is not None:
        _validate_system_prompt(body.system_prompt)
    result = await db.execute(
        select(Agent).where(
            Agent.id == uuid.UUID(agent_id),
            Agent.tenant_id == uuid.UUID(tenant_id),
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found.")

    update_data = body.model_dump(exclude_unset=True)

    if "agent_config" in update_data and update_data["agent_config"] is not None:
        incoming_config = update_data.pop("agent_config")
        current_config = copy.deepcopy(agent.agent_config) if agent.agent_config else {}
        for key, value in incoming_config.items():
            # Only merge dicts; treat escalation_config and similar blobs as atomic replacements
            if isinstance(value, dict) and key in current_config and isinstance(current_config[key], dict) and key not in ["escalation_config"]:
                current_config[key] = {**current_config[key], **value}
            else:
                current_config[key] = value
        agent.agent_config = current_config

    for field, value in update_data.items():
        if field == "is_active":
            if value is True:
                await AgentStateMachine.activate(
                    agent, db=db, actor="user", reason="updated_via_api"
                )
            else:
                await AgentStateMachine.archive(
                    agent, db=db, actor="user", reason="deactivated_via_api"
                )
        elif field != "agent_config":
            setattr(agent, field, value)

    await db.commit()
    await db.refresh(agent)
    return await _agent_to_response(agent, db)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    agent_id: str,
    request: Request,
    _role: str = require_forwarded_role("admin"),
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
):
    """Deactivate an agent (transition to ARCHIVED state)."""
    from app.services.agent_lifecycle import transition_agent, AgentLifecycleError

    result = await db.execute(
        select(Agent).where(
            Agent.id == uuid.UUID(agent_id),
            Agent.tenant_id == uuid.UUID(tenant_id),
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found.")

    try:
        await transition_agent(
            agent,
            "archived",
            db,
            actor_id=tenant_id,
            reason="user_delete",
            request_id=request.headers.get("X-Trace-ID"),
        )
    except AgentLifecycleError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    agent.deleted_at = datetime.now(timezone.utc)
    await AgentStateMachine.archive(agent, db=db, actor="user", reason="deleted_via_api")
    await db.commit()


@router.post("/{agent_id}/restore", response_model=AgentResponse)
async def restore_agent(
    agent_id: str,
    request: Request,
    _role: str = require_forwarded_role("admin"),
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
):
    """
    Restore an archived (soft-deleted) agent.

    - Calls the API Gateway sync-subscription endpoint to verify the subscription status
      with Stripe before activating the agent.
    - If the subscription is valid (active/trialing), the agent is restored as active.
    - If the subscription is invalid or missing, the agent is restored as INACTIVE
      (is_active=False) so the user must complete payment.
    """
    from app.services.agent_lifecycle import transition_agent, AgentLifecycleError

    result = await db.execute(
        select(Agent).where(
            Agent.id == uuid.UUID(agent_id),
            Agent.tenant_id == uuid.UUID(tenant_id),
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found.")

    from app.core.config import settings
    import httpx
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)

    # ── CASE 1: Remaining paid time ────────────────────────────────────────
    # The user already paid through expires_at. Restore immediately — no new
    # payment needed. The existing Stripe subscription (if any) keeps running
    # and will bill normally at the next period end.
    if agent.expires_at and agent.expires_at.replace(tzinfo=timezone.utc) > now:
        days_remaining = (agent.expires_at.replace(tzinfo=timezone.utc) - now).days
        agent.deleted_at = None
        await AgentStateMachine.activate(
            agent, db=db, actor="user",
            reason="restored_within_paid_period"
        )
        await db.commit()
        await db.refresh(agent)
        logger.info(
            "agent_restored_within_paid_period",
            agent_id=agent_id,
            tenant_id=tenant_id,
            expires_at=str(agent.expires_at),
            days_remaining=days_remaining,
        )
        response = await _agent_to_response(agent, db)
        response["days_remaining"] = days_remaining
        return response

    # ── CASE 2: Check whether the Stripe subscription is still active ──────
    has_paid_subscription = False
    if agent.stripe_subscription_id:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                sync_response = await client.post(
                    f"{settings.API_GATEWAY_URL}/api/v1/billing/sync-subscription",
                    headers={
                        "X-Tenant-ID": tenant_id,
                        "X-Internal-Key": settings.INTERNAL_API_KEY,
                    },
                )
                if sync_response.status_code == 200:
                    sync_data = sync_response.json()
                    has_paid_subscription = sync_data.get("status") == "active"
                else:
                    logger.warning("subscription_sync_failed_on_restore",
                                   agent_id=agent_id, status=sync_response.status_code)
        except Exception as e:
            logger.warning("subscription_sync_error_on_restore",
                           agent_id=agent_id, error=str(e))

    if has_paid_subscription:
        agent.deleted_at = None
        await AgentStateMachine.activate(
            agent, db=db, actor="user",
            reason="restored_with_active_subscription"
        )
        await db.commit()
        await db.refresh(agent)
        logger.info("agent_restored", agent_id=agent_id, tenant_id=tenant_id,
                    is_active=True)
        return await _agent_to_response(agent, db)

    # ── CASE 3: Payment required — get a reactivation checkout URL ─────────
    # Ask the API Gateway to create a Stripe checkout for this specific agent.
    # The checkout metadata carries agent_id so the webhook activates it on
    # success without charging for any days already covered by expires_at.
    checkout_url: str | None = None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            reactivation_payload: dict = {
                "agent_id": agent_id,
                "return_path": f"/dashboard/agents",
            }
            # If the old subscription covered future time (edge case: Stripe
            # cancelled mid-cycle), pass paid_through so Stripe sets trial_end.
            if agent.expires_at:
                reactivation_payload["paid_through"] = agent.expires_at.isoformat()

            resp = await client.post(
                f"{settings.API_GATEWAY_URL}/api/v1/billing/reactivation-session",
                json=reactivation_payload,
                headers={
                    "X-Tenant-ID": tenant_id,
                    "X-Internal-Key": settings.INTERNAL_API_KEY,
                },
            )
            if resp.status_code == 200:
                checkout_url = resp.json().get("checkout_url")
    except Exception as e:
        logger.warning("reactivation_checkout_error", agent_id=agent_id, error=str(e))

    # Mark the agent as pending payment (but keep it soft-restored so it shows
    # in the list with a "complete payment" call-to-action).
    agent.deleted_at = None
    await AgentStateMachine.pending_payment(
        agent, db=db, actor="user",
        reason="restored_awaiting_payment"
    )
    await db.commit()
    await db.refresh(agent)

    logger.info("agent_restore_payment_required", agent_id=agent_id,
                tenant_id=tenant_id, checkout_url=bool(checkout_url))

    raise HTTPException(
        status_code=402,
        detail={
            "message": "Payment required to reactivate this agent.",
            "checkout_url": checkout_url,
            "agent_id": agent_id,
        },
    )


_GREETING_AUDIO_DIR = Path(os.environ.get("GREETING_AUDIO_PATH", "/tmp/voice-greetings"))
_GREETING_CDN_BASE = os.environ.get("GREETING_CDN_BASE", "/agent-greetings")


@router.post("/{agent_id}/voice-greeting", status_code=200)
async def upload_voice_greeting(
    agent_id: str,
    request: Request,
    audio: UploadFile = File(..., description="Recorded greeting audio (webm/mp3/wav, max 5 MB)"),
    db: AsyncSession = Depends(get_tenant_db),
):
    """
    Upload a pre-recorded voice greeting for an agent.
    The audio is stored on disk and the URL is saved on the agent.
    Returns {"url": "..."}
    """
    tenant_id = _tenant_id(request)
    result = await db.execute(
        select(Agent).where(
            Agent.id == uuid.UUID(agent_id),
            Agent.tenant_id == uuid.UUID(tenant_id),
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found.")

    # Validate size (5 MB max)
    data = await audio.read(5 * 1024 * 1024 + 1)
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Audio file too large (max 5 MB).")

    # Validate file type via magic bytes rather than trusting Content-Type header.
    # Mapping: magic prefix (bytes) → allowed extension
    _AUDIO_MAGIC: list[tuple[bytes, str]] = [
        (b"ID3", "mp3"),        # MP3 with ID3 tag
        (b"\xff\xfb", "mp3"),   # MP3 frame sync
        (b"\xff\xf3", "mp3"),
        (b"\xff\xf2", "mp3"),
        (b"RIFF", "wav"),       # WAV (RIFF container)
        (b"\x1aE\xdf\xa3", "webm"),  # WebM / MKV
        (b"OggS", "ogg"),       # Ogg container
    ]
    ext: str | None = None
    for magic, candidate_ext in _AUDIO_MAGIC:
        if data[:len(magic)] == magic:
            ext = candidate_ext
            break
    # For WAV, also verify the sub-chunk type
    if ext == "wav" and len(data) >= 12 and data[8:12] not in (b"WAVE",):
        ext = None
    if ext is None:
        raise HTTPException(status_code=400, detail="Unsupported or invalid audio format.")

    _GREETING_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    # Use a UUID-based filename to prevent predictable overwrites and path
    # collision when an agent re-uploads a greeting.
    file_uuid = uuid.uuid4()
    filename = f"{agent_id}_{file_uuid}.{ext}"
    filepath = _GREETING_AUDIO_DIR / filename

    filepath.write_bytes(data)

    url = f"{_GREETING_CDN_BASE}/{filename}"
    agent.voice_greeting_url = url
    await db.commit()

    logger.info("voice_greeting_uploaded", agent_id=agent_id, url=url)
    return {"url": url}


@router.delete("/{agent_id}/voice-greeting", status_code=200)
async def delete_voice_greeting(
    agent_id: str,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
):
    """Remove the pre-recorded voice greeting from an agent."""
    tenant_id = _tenant_id(request)
    result = await db.execute(
        select(Agent).where(
            Agent.id == uuid.UUID(agent_id),
            Agent.tenant_id == uuid.UUID(tenant_id),
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found.")

    # Delete file if present
    if agent.voice_greeting_url:
        filename = Path(agent.voice_greeting_url).name
        filepath = _GREETING_AUDIO_DIR / filename
        if filepath.exists():
            filepath.unlink(missing_ok=True)
    agent.voice_greeting_url = None
    await db.commit()
    return {"ok": True}


@router.post("/{agent_id}/escalation/test", response_model=ConnectorTestResult)
async def test_escalation_connector(
    agent_id: str,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
):
    """Test connector credentials without firing a real escalation."""
    from app.connectors.factory import get_connector

    tenant_id = _tenant_id(request)
    result = await db.execute(
        select(Agent).where(
            Agent.id == uuid.UUID(agent_id),
            Agent.tenant_id == uuid.UUID(tenant_id),
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found.")

    agent_cfg = agent.agent_config or {}
    escalation_config = agent_cfg.get("escalation_config", {}) or {}
    connector_type = (escalation_config.get("connector_type") or "").strip()
    if not connector_type:
        raise HTTPException(status_code=400, detail="No connector_type configured for this agent.")

    connector = get_connector(escalation_config)
    if connector is None:
        raise HTTPException(status_code=400, detail=f"Unknown connector type: {connector_type!r}")

    t0 = time.monotonic()
    success, message = await connector.validate_credentials()
    latency_ms = int((time.monotonic() - t0) * 1000)

    logger.info(
        "connector_test",
        agent_id=agent_id,
        connector_type=connector_type,
        success=success,
        latency_ms=latency_ms,
    )
    return ConnectorTestResult(
        success=success,
        connector_type=connector_type,
        message=message or ("Connected successfully" if success else "Validation failed"),
        latency_ms=latency_ms,
    )


@router.post("/{agent_id}/test", response_model=ChatResponse)
async def test_agent(
    agent_id: str,
    body: AgentTestRequest,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
):
    """Send a test message to an agent."""
    from app.schemas.chat import ChatRequest
    chat_body = ChatRequest(
        agent_id=agent_id,
        message=body.message,
        channel="text",
        customer_identifier=body.customer_identifier or "test-user",
    )
    # Delegate to the chat endpoint
    from app.api.v1.chat import chat
    return await chat(chat_body, request, db)
