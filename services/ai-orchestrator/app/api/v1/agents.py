from __future__ import annotations

import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_tenant_db, get_current_tenant, require_forwarded_role
from app.models.agent import Agent, AgentPlaybook
from app.schemas.chat import (
    AgentCreate,
    AgentResponse,
    AgentTestRequest,
    AgentUpdate,
    ChatResponse,
    ConnectorTestResult,
)
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
    supported_langs = getattr(agent, 'supported_languages', None) or []
    
    # Generate dynamic components from platform settings
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
        voice_enabled=agent.voice_enabled,
        voice_id=agent.voice_id,
        language=agent.language,
        auto_detect_language=getattr(agent, 'auto_detect_language', False),
        supported_languages=supported_langs,
        greeting_message=agent.greeting_message,
        voice_greeting_url=agent.voice_greeting_url,
        voice_system_prompt=agent.voice_system_prompt,
        computed_greeting=computed_greeting,
        computed_protocol=computed_protocol,
        computed_fallback=computed_fallback,
        tools=agent.tools or [],
        knowledge_base_ids=agent.knowledge_base_ids or [],
        llm_config=agent.llm_config or {},
        escalation_config=agent.escalation_config or {},
        is_active=agent.is_active,
        stripe_subscription_id=agent.stripe_subscription_id,
        deleted_at=agent.deleted_at.isoformat() if agent.deleted_at else None,
        created_at=agent.created_at.isoformat() if agent.created_at else None,
        updated_at=agent.updated_at.isoformat() if agent.updated_at else None,
    )


@router.post("", response_model=AgentResponse, status_code=201)
async def create_agent(
    body: AgentCreate,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
):
    """Create a new AI agent for the tenant."""
    tenant_id = _tenant_id(request)
    _validate_system_prompt(body.system_prompt)
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
        tools=body.tools,
        knowledge_base_ids=body.knowledge_base_ids,
        llm_config=body.llm_config.model_dump() if body.llm_config else {},
        escalation_config=body.escalation_config.model_dump() if body.escalation_config else {},
        greeting_message=f"Hi! I'm {body.name}. How can I help you today?",
        voice_system_prompt=body.voice_system_prompt,
        is_active=True,
    )
    db.add(agent)

    # Auto-create a default playbook so the agent is ready to use immediately
    tenant_uuid = uuid.UUID(tenant_id)
    default_playbook = AgentPlaybook(
        id=uuid.uuid4(),
        agent_id=agent.id,
        tenant_id=tenant_uuid,  # must be the TENANT's UUID, not the agent's
        name="Default",
        description="Default playbook — edit to add instructions for your agent.",
        is_default=True,
        intent_triggers=[],
        instructions=body.system_prompt or "",
        tone=body.personality or "professional",
    )
    db.add(default_playbook)

    # Auto-create a "General Chat" default playbook for handling unmatched messages
    general_chat_playbook = AgentPlaybook(
        id=uuid.uuid4(),
        agent_id=agent.id,
        tenant_id=tenant_uuid,
        name="General Chat",
        description="Handle general conversations and questions not covered by other playbooks",
        is_active=True,
        intent_triggers=[],
        instructions=body.system_prompt or "",
        tone=body.personality or "professional",
    )
    db.add(general_chat_playbook)

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
    # Safety guard: is_active must never be mutated directly via PATCH.
    # Use DELETE /agents/{id} to deactivate or POST /agents/{id}/restore to reactivate.
    update_data.pop("is_active", None)
    for field, value in update_data.items():
        # Serialize Pydantic sub-models to plain dicts for JSONB columns
        if hasattr(value, "model_dump"):
            value = value.model_dump()
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

    await db.commit()


@router.post("/{agent_id}/restore", response_model=AgentResponse)
async def restore_agent(
    agent_id: str,
    request: Request,
    _role: str = require_forwarded_role("admin"),
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
):
    """Restore an archived agent (transition back to ACTIVE state)."""
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
            "active",
            db,
            actor_id=tenant_id,
            reason="user_restore",
            request_id=request.headers.get("X-Trace-ID"),
        )
    except AgentLifecycleError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    await db.commit()
    await db.refresh(agent)
    return await _agent_to_response(agent, db)


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

    escalation_config = agent.escalation_config or {}
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
