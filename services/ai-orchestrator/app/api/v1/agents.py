from __future__ import annotations

import copy
import os
import re
import time
import uuid
import json
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List
from fastapi.responses import StreamingResponse as _StreamingResponse

import structlog
from fastapi import APIRouter,BackgroundTasks, Depends, File, HTTPException, Request, UploadFile, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified
from app.core.redis_client import get_redis as _get_redis


from shared.pii import redact
import shared.pii as pii_service

def _has_variables(text: str | None) -> bool:
    if not text:
        return False
    return bool(re.search(r'\$\[vars:\w+\]|\$vars:\w+', text))

def _delete_old_audio(url: str | None) -> None:
    if not url:
        return
    try:
        from pathlib import Path
        import os
        audio_dir = Path(os.environ.get("GREETING_AUDIO_PATH", "/tmp/voice-greetings"))
        filename = Path(url).name
        filepath = audio_dir / filename
        if filepath.exists():
            filepath.unlink(missing_ok=True)
            logger.info("deleted_old_audio", filepath=str(filepath))
    except Exception as e:
        logger.warning("failed_to_delete_old_audio", url=url, error=str(e))

from app.core.database import get_db, AsyncSessionLocal
from app.core.security import get_tenant_db, get_current_tenant, require_forwarded_role, require_internal_key
from app.models.agent import Agent, AgentPlaybook, AgentGuardrails
from app.schemas.chat import (
    AgentCreate,
    AgentResponse,
    AgentTestRequest,
    AgentUpdate,
    ChatResponse,
    ConnectorTestResult,
)
from shared.orchestration.agent_state_machine import AgentStateMachine
from app.guardrails.voice_agent_guardrails import (
    get_dynamic_voice_protocol,
    generate_multilingual_greeting,
    generate_multilingual_fallback,
    get_or_compute_voice_strings,
    generate_ivr_language_prompt,
)
from shared.orchestration.tts_generation_service import TTSGenerationService
from app.utils.expansion import resolve_agent_variables
from app.models.variable import AgentVariable
from shared.orchestration.mcp_client import MCPClient
from app.core.config import settings

logger = structlog.get_logger(__name__)
router = APIRouter()

# Module-level TTS generation service — shared across all agent endpoints.
# Uses settings defaults; storage path and CDN base reuse the same directory
# as the manual voice-greeting upload endpoint below.
_tts_service = TTSGenerationService(
    storage_path=os.environ.get("GREETING_AUDIO_PATH", "/tmp/voice-greetings"),
    cdn_base=os.environ.get("GREETING_CDN_BASE", "/agent-greetings"),
)

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


async def _background_purge_agent_knowledge(agent_id: str, tenant_id: str):
    """Purge all RAG chunks from MCP for a specific agent when archived or deleted."""
    from shared.orchestration.mcp_client import MCPClient
    from app.core.config import settings
    mcp = MCPClient(base_url=settings.MCP_SERVER_URL, ws_url=settings.MCP_WS_URL)
    try:
        await mcp.initialize()
        # Find the KB ID for this agent
        kb_id = await mcp.get_or_create_agent_kb(tenant_id, agent_id, "unknown")
        # Cleanup all chunks for this agent ID (the extra metadata layer)
        count = await mcp.cleanup_knowledge_by_metadata(tenant_id, kb_id, "agent_id", agent_id)
        logger.info("agent_knowledge_purged_on_lifecycle_event", agent_id=agent_id, chunks_purged=count)
        await mcp.close()
    except Exception as e:
        logger.error("agent_knowledge_purge_failed", agent_id=agent_id, error=str(e))


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


def _restricted_agent_id(request: Request) -> uuid.UUID | None:
    """Extract optional agent restriction passed by the API Gateway proxy."""
    raid = request.headers.get("X-Restricted-Agent-ID")
    if raid:
        try:
            return uuid.UUID(raid)
        except ValueError:
            return None
    return None


async def _agent_to_response(agent: Agent, db: AsyncSession) -> AgentResponse:
    config = agent.agent_config or {}
    supported_langs = config.get("supported_languages", [])

    # Use cached values when available; compute and persist on first call.
    computed_greeting, computed_protocol, computed_fallback = await get_or_compute_voice_strings(db, agent)
    config = agent.agent_config or {}  # re-read after possible cache write

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
        ivr_language_prompt=config.get("ivr_language_prompt"),
        voice_greeting_url=config.get("voice_greeting_url"),
        ivr_language_url=config.get("ivr_language_url"),
        opening_audio_url=config.get("opening_audio_url"),
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
        status=agent.status or "DRAFT",
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
    from shared.orchestration.settings_service import SettingsService
    guardrails_setting = await SettingsService.get_setting(db, "platform_guardrails", default={})
    # Handle both wrapped {rules: [...]} and direct list/dict formats
    if isinstance(guardrails_setting, dict) and "rules" in guardrails_setting:
        guardrails = guardrails_setting["rules"]
    elif isinstance(guardrails_setting, list):
        guardrails = guardrails_setting
    else:
        # If it's a dict (like {} from defaults), just return an empty list
        # since the frontend expects an array to call .reduce() on.
        guardrails = []
    return {"guardrails": guardrails}


@router.get("/{agent_id}/opening-preview")
async def get_agent_opening_preview(
    agent_id: str,
    request: Request,
    language: Optional[str] = None,
    supported_languages: Optional[str] = None,  # comma-separated
    greeting: Optional[str] = None,
    ivr_prompt: Optional[str] = None,
    db: AsyncSession = Depends(get_tenant_db),
):
    """
    Get the full mandatory opening text (Greeting + Language Assistance).
    Used by the dashboard to show an accurate preview of the agent's entrance.
    Supports previewing un-saved changes via query parameters.
    """
    tenant_id = _tenant_id(request)
    
    # Apply isolation (CRIT-005)
    raid = _restricted_agent_id(request)
    if raid and uuid.UUID(agent_id) != raid:
        raise HTTPException(status_code=404, detail="Agent not found.")

    result = await db.execute(
        select(Agent).where(
            Agent.id == uuid.UUID(agent_id),
            Agent.tenant_id == uuid.UUID(tenant_id),
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found.")

    # Resolve variables for preview without PII scrubbing
    result_vars = await db.execute(select(AgentVariable).where(AgentVariable.agent_id == agent.id))
    variables = result_vars.scalars().all()

    # If the operator has provided a specific IVR prompt (even if it's currently unsaved in the UI),
    # we preview that EXACTLY. This prevents the "double-greeting" bug where the preview
    # prepends the chat greeting to a voice greeting that already contains it.
    if ivr_prompt:
        resolved_text = resolve_agent_variables(ivr_prompt, agent, variables, clean=True, redact=False)
        return {"text": resolved_text}

    # Otherwise, compute the automatic combination
    active_lang = language or agent.language
    agent_primary_lang = agent.language or "en"

    if supported_languages is not None:
        supported_langs = [l.strip() for l in supported_languages.split(",") if l.strip()]
    else:
        supported_langs = (agent.agent_config or {}).get("supported_languages", [])

    base_lang = active_lang.split("-")[0]
    primary_base = agent_primary_lang.split("-")[0]
    if base_lang == primary_base:
        custom_greeting = greeting if greeting is not None else (
            (agent.agent_config or {}).get("greeting_message")
        )
    else:
        custom_greeting = None

    full_text = await generate_multilingual_greeting(db, active_lang, supported_langs, custom_greeting=custom_greeting, redact=False)
    ivr_generated = await generate_ivr_language_prompt(db, supported_langs)
    
    combined_text = full_text
    if ivr_generated:
        combined_text += f" {ivr_generated}"

    resolved_text = resolve_agent_variables(combined_text, agent, variables, clean=True, redact=False)

    return {"text": resolved_text}


@router.put("/platform/global-guardrails")
async def update_platform_global_guardrails(
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    """Update global guardrails (admin only). Writes to DB and updates Redis cache."""
    from shared.orchestration.settings_service import SettingsService
    guardrails = body.get("guardrails", [])

    await db.execute(
        text("INSERT INTO platform_settings (key, value) VALUES ('platform_guardrails', :value) "
             "ON CONFLICT (key) DO UPDATE SET value = :value"),
        {"value": json.dumps(guardrails)}
    )
    await db.commit()

    await SettingsService.invalidate_cache("platform_guardrails")
    logger.info("global_guardrails_updated", count=len(guardrails))
    return guardrails


@router.post("", response_model=AgentResponse, status_code=201)
async def create_agent(
    body: AgentCreate,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
    _internal: bool = Depends(require_internal_key),
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
    
    # If the agent is inactive, it requires payment. Transition its lifecycle state.
    if not agent.is_active:
        from shared.orchestration.agent_state_machine import AgentStateMachine as _AgentStateMachine
        await _AgentStateMachine.pending_payment(
            agent, db=db, actor="user", reason="created_without_slot"
        )

    tenant_uuid = uuid.UUID(tenant_id)
    

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

    # P0 Compliance: Force PII redaction for medical agents
    pii_redaction_default = False
    if body.business_type == "medical":
        pii_redaction_default = True
        logger.info("enforcing_pii_redaction_for_medical_agent", tenant_id=tenant_id)

    # Merge any guardrails_config provided at creation time (e.g. from template instantiation)
    initial_guardrails_cfg = {
        "profanity_filter": True,
        "pii_redaction": pii_redaction_default,
        "pii_pseudonymization": True,
        "is_active": True,
    }
    if body.guardrails_config:
        # Caller-provided config wins, but defaults fill any gaps
        initial_guardrails_cfg.update(body.guardrails_config)
        logger.info("guardrails_config_from_request", tenant_id=tenant_id, keys=list(body.guardrails_config.keys()))

    default_guardrails = AgentGuardrails(
        id=uuid.uuid4(),
        agent_id=agent.id,
        tenant_id=tenant_uuid,
        config=initial_guardrails_cfg,
        is_active=True,
    )
    db.add(default_guardrails)

    await db.commit()
    await db.refresh(agent)

    # Auto-generate TTS audio for voice agents when greeting text is provided.
    # This runs after commit so the agent already has a stable ID in the DB.
    
    # 1. First, automatically predefine ivr_language_prompt if supported_languages provided but prompt is empty
    cfg = agent.agent_config or {}
    supported_langs = cfg.get("supported_languages", [])
    if supported_langs and not cfg.get("ivr_language_prompt"):
        new_prompt = await generate_ivr_language_prompt(db, supported_langs)
        if new_prompt:
            new_cfg = dict(agent.agent_config)
            new_cfg["ivr_language_prompt"] = new_prompt
            agent.agent_config = new_cfg
            await db.commit()
            await db.refresh(agent)
            cfg = agent.agent_config
            logger.info("ivr_prompt_auto_populated_on_create", agent_id=str(agent.id))

    # --- TEMPLATE INSTANTIATION HOOK (Immediate Activation) ---
    if agent.is_active and agent.agent_config and "template_context" in agent.agent_config:
        ctx = agent.agent_config.pop("template_context")
        flag_modified(agent, "agent_config")
        try:
            from app.api.v1.templates import process_template_instantiation
            _bg_tasks = BackgroundTasks()
            _actor_info = {
                "actor_email": request.headers.get("X-Actor-Email", "system"),
                "is_support_access": request.headers.get("X-Is-Support-Access", "false").lower() == "true",
                "trace_id": request.headers.get("X-Trace-ID", "unknown"),
            }
            await process_template_instantiation(
                t_uuid=uuid.UUID(ctx.get("template_id")),
                v_uuid=uuid.UUID(ctx.get("template_version_id")),
                agent=agent,
                tenant=tenant_id,
                db=db,
                request=request,
                background_tasks=_bg_tasks,
                variable_values=ctx.get("variable_values", {}),
                tool_configs=ctx.get("tool_configs", {}),
                actor_info=_actor_info,
            )
            logger.info("immediate_template_instantiated", agent_id=str(agent.id))
        except Exception as e:
            logger.error("failed_to_instantiate_immediate_template", error=str(e), agent_id=str(agent.id))

    if agent.voice_enabled:
        voice_id = agent.voice_id or "alloy"
        tts_updated = False

        greeting_text = cfg.get("greeting_message")
        if greeting_text and not cfg.get("voice_greeting_url"):
            _validate_system_prompt(greeting_text)
            if not _has_variables(greeting_text):
                redacted_text = redact(greeting_text)
                url = await _tts_service.generate_greeting(
                    text=redacted_text,
                    voice_id=voice_id,
                    agent_id=str(agent.id),
                )
                if url:
                    new_cfg = dict(agent.agent_config)
                    new_cfg["voice_greeting_url"] = url
                    agent.agent_config = new_cfg
                    tts_updated = True
                    logger.info("voice_greeting_generated", agent_id=str(agent.id), url=url)

        ivr_text = cfg.get("ivr_language_prompt")
        if ivr_text and not cfg.get("ivr_language_url"):
            if not _has_variables(ivr_text):
                redacted_ivr = redact(ivr_text)
                url = await _tts_service.generate_ivr_prompt(
                    text=redacted_ivr,
                    voice_id=voice_id,
                    agent_id=str(agent.id),
                )
                if url:
                    new_cfg = dict(agent.agent_config)
                    new_cfg["ivr_language_url"] = url
                    agent.agent_config = new_cfg
                    tts_updated = True
                    logger.info("ivr_prompt_generated", agent_id=str(agent.id), url=url)

        if tts_updated:
            await db.commit()
            await db.refresh(agent)

        try:
            # Generate mandatory opening audio
            # (Greeting + Language Assistance)
            supported_langs = cfg.get("supported_languages", [])
            custom_greeting = (agent.agent_config or {}).get("greeting_message")
            opening_text = await generate_multilingual_greeting(db, agent.language, supported_langs, custom_greeting=custom_greeting)
            if opening_text:
                if not _has_variables(opening_text):
                    redacted_opening = redact(opening_text)
                    url = await _tts_service.generate_opening(
                        text=redacted_opening,
                        voice_id=voice_id,
                        agent_id=str(agent.id),
                    )
                    if url:
                        new_cfg = dict(agent.agent_config)
                        new_cfg["opening_audio_url"] = url
                        agent.agent_config = new_cfg
                        await db.commit()
                        await db.refresh(agent)
                        logger.info("voice_opening_generated", agent_id=str(agent.id), url=url)
        except Exception as tts_err:
            logger.error("voice_opening_generation_failed", agent_id=str(agent.id), error=str(tts_err))

    logger.info(
        "agent_created",
        agent_id=str(agent.id),
        tenant_id=tenant_id,
        actor_email=request.headers.get("X-Actor-Email", "unknown"),
    )
    return await _agent_to_response(agent, db)


@router.get("/available-as-tools", response_model=list[AgentResponse])
async def list_agents_available_as_tools(
    exclude_id: Optional[str] = None,
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
    request: Request = None, # Added request to access headers
):
    """
    Return all ACTIVE agents in the tenant that are marked is_available_as_tool=True.
    Optionally exclude a specific agent ID (e.g., the caller agent itself).
    Used to populate the 'Agent Tools' section of the tools marketplace.
    """
    # Apply isolation (CRIT-005)
    raid = _restricted_agent_id(request) if request else None

    query = select(Agent).where(
        Agent.tenant_id == uuid.UUID(tenant_id),
        Agent.status == "ACTIVE",
        Agent.is_available_as_tool == True,  # noqa: E712
    )
    if raid:
        query = query.where(Agent.id == raid)

    if exclude_id:
        try:
            query = query.where(Agent.id != uuid.UUID(exclude_id))
        except ValueError:
            pass

    result = await db.execute(query.order_by(Agent.name))
    agents = result.scalars().all()
    return [await _agent_to_response(a, db) for a in agents]


@router.get("", response_model=list[AgentResponse])
async def list_agents(
    request: Request,
    status: str = "active",  # active | archived | draft | pending_payment | all
    page: int = 1,
    limit: int = 50,
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
):
    """
    List agents for the tenant (paginated).
    - status=active (default): Agent.status=ACTIVE
    - status=archived: Agent.status=ARCHIVED
    - status=draft: Agent.status=DRAFT
    - status=pending_payment: Agent.status=PENDING_PAYMENT
    - status=all: everything
    """
    page = max(1, page)
    limit = min(max(1, limit), 200)
    offset = (page - 1) * limit

    query = select(Agent).where(Agent.tenant_id == uuid.UUID(tenant_id))
    
    # Apply isolation (CRIT-005)
    raid = _restricted_agent_id(request) if request else None
    if raid:
        query = query.where(Agent.id == raid)

    status_upper = status.upper()
    if status_upper == "ACTIVE":
        query = query.where(Agent.status == "ACTIVE")
    elif status_upper == "ARCHIVED":
        query = query.where(Agent.status == "ARCHIVED")
    elif status_upper == "DRAFT":
        query = query.where(Agent.status == "DRAFT")
    elif status_upper == "PENDING_PAYMENT":
        query = query.where(Agent.status == "PENDING_PAYMENT")
    elif status_upper == "INACTIVE":
        # Legacy compat: inactive = any non-active state except archived
        query = query.where(Agent.status.in_(["DRAFT", "PENDING_PAYMENT", "GRACE", "EXPIRED"]))
    # else "ALL" — no filter

    result = await db.execute(
        query.order_by(Agent.created_at.desc(), Agent.id.desc()).limit(limit).offset(offset)
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
    
    # Apply isolation (CRIT-005)
    raid = _restricted_agent_id(request)
    if raid and uuid.UUID(agent_id) != raid:
        raise HTTPException(status_code=404, detail="Agent not found.")

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


@router.post("/{agent_id}/archive", response_model=AgentResponse)
async def archive_agent(
    agent_id: str,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
    _internal: bool = Depends(require_internal_key),
):
    """
    Archive an agent, freeing its slot for reuse.

    The agent retains all configuration and can be revived later.
    Called by the API Gateway swap flow.
    (Phase 8: Purges vector index to Cold Storage)
    """
    tenant_id = _tenant_id(request)
    
    # Apply isolation (CRIT-005)
    raid = _restricted_agent_id(request)
    if raid and uuid.UUID(agent_id) != raid:
        raise HTTPException(status_code=404, detail="Agent not found.")

    result = await db.execute(
        select(Agent).where(
            Agent.id == uuid.UUID(agent_id),
            Agent.tenant_id == uuid.UUID(tenant_id),
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found.")

    if agent.status == "ARCHIVED":
        return await _agent_to_response(agent, db)

    ok = await AgentStateMachine.deactivate(
        agent, db=db, actor="operator", reason="operator_archived_to_free_slot"
    )
    if not ok:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot archive agent from state '{agent.status}'.",
        )

    await db.commit()
    await db.refresh(agent)
    
    # Phase 8: Purge vector index for archived/cold agent
    tasks = BackgroundTasks()
    tasks.add_task(_background_purge_agent_knowledge, agent_id, tenant_id)
    
    logger.info(
        "agent_archived",
        agent_id=agent_id,
        tenant_id=tenant_id,
        actor_email=request.headers.get("X-Actor-Email", "unknown"),
    )
    return await _agent_to_response(agent, db)


@router.post("/{agent_id}/activate", response_model=AgentResponse)
async def activate_agent(
    agent_id: str,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
    _internal: bool = Depends(require_internal_key),
):
    """
    Activate/revive an agent once a free slot is confirmed.
    Requires X-Internal-Key validation (enforced by require_internal_key dependency).
    """


    tenant_id = _tenant_id(request)
    
    # Apply isolation (CRIT-005)
    raid = _restricted_agent_id(request)
    if raid and uuid.UUID(agent_id) != raid:
        raise HTTPException(status_code=404, detail="Agent not found.")

    result = await db.execute(
        select(Agent).where(
            Agent.id == uuid.UUID(agent_id),
            Agent.tenant_id == uuid.UUID(tenant_id),
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found.")

    if agent.status == "ACTIVE":
        return await _agent_to_response(agent, db)

    ok = await AgentStateMachine.revive(
        agent, db=db, actor="slot_manager", reason="operator_slot_assigned"
    )
    if not ok:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot activate agent from state '{agent.status}'.",
        )

    # Optionally link the slot subscription details
    try:
        body = await request.json()
        if body.get("stripe_subscription_id"):
            agent.stripe_subscription_id = body["stripe_subscription_id"]
        if body.get("expires_at"):
            agent.expires_at = datetime.fromisoformat(body["expires_at"])
    except Exception:
        pass

    # --- TEMPLATE INSTANTIATION HOOK ---
    # If the agent was created with a template and is now being activated,
    # process the instantiation (populating playbooks, prompts, tools).
    if agent.agent_config and "template_context" in agent.agent_config:
        ctx = agent.agent_config.pop("template_context")
        flag_modified(agent, "agent_config")
        try:
            from app.api.v1.templates import process_template_instantiation
            _bg_tasks = BackgroundTasks()
            _actor_info = {
                "actor_email": request.headers.get("X-Actor-Email", "billing_webhook"),
                "is_support_access": request.headers.get("X-Is-Support-Access", "false").lower() == "true",
                "trace_id": request.headers.get("X-Trace-ID", "unknown"),
            }
            await process_template_instantiation(
                t_uuid=uuid.UUID(ctx.get("template_id")),
                v_uuid=uuid.UUID(ctx.get("template_version_id")),
                agent=agent,
                tenant=tenant_id,  # must be str, not uuid.UUID
                db=db,
                request=request,
                background_tasks=_bg_tasks,
                variable_values=ctx.get("variable_values", {}),
                tool_configs=ctx.get("tool_configs", {}),
                actor_info=_actor_info,
            )
            logger.info("activation_template_instantiated", agent_id=str(agent.id))
        except Exception as e:
            logger.error("failed_to_instantiate_template_on_activation", error=str(e), agent_id=str(agent.id))

    await db.commit()
    await db.refresh(agent)

    # Notify any open SSE listeners
    try:
        from app.core.redis_client import get_redis as _get_redis
        redis = await _get_redis()
        await redis.publish(
            f"agent:activated:{agent_id}",
            json.dumps({"status": "active", "agent_id": agent_id}),
        )
    except Exception as pub_err:
        logger.warning("agent_activate_redis_notify_failed", error=str(pub_err))

    logger.info(
        "agent_activated_via_slot",
        agent_id=agent_id,
        tenant_id=tenant_id,
        actor_email=request.headers.get("X-Actor-Email", "unknown"),
    )
    return await _agent_to_response(agent, db)


@router.get("/{agent_id}/activation-stream")

async def agent_activation_stream(
    agent_id: str,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
):
    """
    SSE stream that closes as soon as the agent transitions to ACTIVE.

    The billing webhook publishes to Redis when it activates the agent.
    The frontend subscribes here instead of polling GET /{agent_id} repeatedly.
    Times out after 40 s and sends {"status":"timeout"} so the client can fall back.
    """

    tenant_id = _tenant_id(request)
    trace_id = request.headers.get("X-Trace-ID") or "unknown"
    logger.info("agent_activation_stream_connected", agent_id=agent_id, tenant_id=tenant_id, trace_id=trace_id)


    # Verify the agent belongs to this tenant before opening the stream.
    # Apply isolation (CRIT-005)
    raid = _restricted_agent_id(request)
    if raid and uuid.UUID(agent_id) != raid:
        raise HTTPException(status_code=404, detail="Agent not found.")

    result = await db.execute(
        select(Agent).where(
            Agent.id == uuid.UUID(agent_id),
            Agent.tenant_id == uuid.UUID(tenant_id),
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found.")

    # If the webhook already fired before the browser opened this connection, close immediately.
    if agent.is_active:
        async def _already_active():
            yield f"data: {json.dumps({'status': 'active', 'agent_id': agent_id})}\n\n"
        return _StreamingResponse(_already_active(), media_type="text/event-stream")

    channel = f"agent:activated:{agent_id}"

    async def _event_stream():
        redis = await _get_redis()
        pubsub = redis.pubsub()
        await pubsub.subscribe(channel)
        
        # RACE CONDITION FIX: Check if the agent became active in the window between 
        # the initial check and the Redis subscription.
        async with AsyncSessionLocal() as check_db:
            result = await check_db.execute(
                select(Agent).where(Agent.id == uuid.UUID(agent_id))
            )
            fresh_agent = result.scalar_one_or_none()
            if fresh_agent and fresh_agent.is_active:
                yield f"data: {json.dumps({'status': 'active', 'agent_id': agent_id})}\n\n"
                await pubsub.unsubscribe(channel)
                await pubsub.aclose()
                return

        try:
            deadline = asyncio.get_event_loop().time() + 45
            while True:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    yield f"data: {json.dumps({'status': 'timeout'})}\n\n"
                    break

                # Periodic DB check to catch state changes if Redis message is missed
                async with AsyncSessionLocal() as poll_db:
                    result = await poll_db.execute(
                        select(Agent).where(Agent.id == uuid.UUID(agent_id))
                    )
                    polled_agent = result.scalar_one_or_none()
                    if polled_agent and polled_agent.is_active:
                        yield f"data: {json.dumps({'status': 'active', 'agent_id': agent_id})}\n\n"
                        break

                # Wait up to 1.5s for a message, then send a keepalive comment.
                try:
                    msg = await asyncio.wait_for(pubsub.get_message(ignore_subscribe_messages=True), timeout=1.5)
                    if msg and msg.get("type") == "message":
                        yield f"data: {msg['data']}\n\n"
                        break
                except asyncio.TimeoutError:
                    # SSE comment — keeps the connection alive through proxies.
                    yield ": keepalive\n\n"
        except asyncio.TimeoutError:
            pass
        except asyncio.CancelledError:
            pass
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()

    return _StreamingResponse(_event_stream(), media_type="text/event-stream")


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
        
    # Apply isolation (CRIT-005)
    raid = _restricted_agent_id(request)
    if raid and uuid.UUID(agent_id) != raid:
        raise HTTPException(status_code=404, detail="Agent not found.")

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

    if "version" in update_data:
        expected_version = update_data.pop("version")
        if expected_version is not None and agent.version != expected_version:
            raise HTTPException(
                status_code=409,
                detail=f"Conflict: Agent was modified by another request. Expected version {expected_version}, got {agent.version}."
            )

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

        # P2 FIX: Validate extension routing targets
        esc_cfg = current_config.get("escalation_config") or {}
        ext_routes = esc_cfg.get("extension_routes", [])
        if ext_routes:
            for route in ext_routes:
                if route.get("target_type") == "agent_id":
                    target_id = route.get("target")
                    if not target_id:
                        continue
                    try:
                        target_uuid = uuid.UUID(target_id)
                        # Check existence within the same tenant
                        t_res = await db.execute(
                            select(Agent.id).where(
                                Agent.id == target_uuid,
                                Agent.tenant_id == uuid.UUID(tenant_id)
                            )
                        )
                        if not t_res.scalar():
                            raise HTTPException(
                                status_code=422,
                                detail=f"Extension target agent {target_id} not found or belongs to another tenant."
                            )
                    except ValueError:
                        raise HTTPException(status_code=422, detail=f"Invalid UUID for extension target: {target_id}")

    # Zero-trust: activating a PENDING_PAYMENT agent requires the billing webhook's
    # internal key — a regular user/frontend call must NOT bypass payment verification.
    from app.core.config import settings as _settings
    _is_internal_caller = (
        request.headers.get("X-Internal-Key") == _settings.INTERNAL_API_KEY
    )

    if "opening_preview" in update_data:
        op = update_data.pop("opening_preview")
        if agent.agent_config is None:
            agent.agent_config = {}
        agent.agent_config["_cached_greeting"] = op
        flag_modified(agent, "agent_config")

    for field, value in update_data.items():
        if field == "is_active":
            if value is True:
                if agent.status == "PENDING_PAYMENT" and not _is_internal_caller:
                    raise HTTPException(
                        status_code=402,
                        detail={
                            "error": "payment_required",
                            "message": "Agent activation requires payment confirmation.",
                        },
                    )
                _actor = "billing_webhook" if _is_internal_caller else "user"
                await AgentStateMachine.activate(
                    agent, db=db, actor=_actor, reason="updated_via_api"
                )

                # --- TEMPLATE INSTANTIATION HOOK ---
                if agent.agent_config and "template_context" in agent.agent_config:
                    ctx = agent.agent_config.pop("template_context")
                    flag_modified(agent, "agent_config")
                    try:
                        from app.api.v1.templates import process_template_instantiation
                        _bg_tasks = BackgroundTasks()
                        _actor_info = {
                            "actor_email": request.headers.get("X-Actor-Email", "billing_webhook"),
                            "is_support_access": request.headers.get("X-Is-Support-Access", "false").lower() == "true",
                            "trace_id": request.headers.get("X-Trace-ID", "unknown"),
                        }
                        await process_template_instantiation(
                            t_uuid=uuid.UUID(ctx.get("template_id")),
                            v_uuid=uuid.UUID(ctx.get("template_version_id")),
                            agent=agent,
                            tenant=tenant_id,
                            db=db,
                            request=request,
                            background_tasks=_bg_tasks,
                            variable_values=ctx.get("variable_values", {}),
                            tool_configs=ctx.get("tool_configs", {}),
                            actor_info=_actor_info,
                        )
                        logger.info("pending_template_instantiated", agent_id=str(agent.id))
                    except Exception as e:
                        logger.error("failed_to_instantiate_pending_template", error=str(e), agent_id=str(agent.id))

                # Notify any open activation-stream SSE connections for this agent.
                if _is_internal_caller:
                    try:
                        from app.core.redis_client import get_redis as _get_redis
                        _redis = await _get_redis()
                        await _redis.publish(
                            f"agent:activated:{agent_id}",
                            json.dumps({"status": "active", "agent_id": agent_id}),
                        )
                    except Exception as _exc:
                        logger.warning("activation_pubsub_publish_failed", error=str(_exc))
            else:
                await AgentStateMachine.archive(
                    agent, db=db, actor="user", reason="deactivated_via_api"
                )
        elif field == "expires_at":
            # expires_at arrives as an ISO-format string from the billing webhook;
            # parse it into a timezone-aware datetime before writing to the DB column.
            if value is None:
                agent.expires_at = None
            elif isinstance(value, str):
                from datetime import datetime, timezone
                try:
                    # Python 3.11+ fromisoformat handles 'Z'; replace for 3.10 compat
                    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    agent.expires_at = dt
                except ValueError:
                    logger.warning("expires_at_parse_failed", value=value, agent_id=agent_id)
            else:
                agent.expires_at = value
        elif field != "agent_config":
            setattr(agent, field, value)

    from sqlalchemy.orm.exc import StaleDataError
    try:
        await db.commit()
    except StaleDataError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Conflict: Agent was modified by another request. Please reload and try again."
        )
    await db.refresh(agent)

    # 1. Auto-populate IVR Language Prompt if supported_languages changed and prompt is empty
    if ("supported_languages" in update_data or 
        ("agent_config" in body.model_dump(exclude_unset=True) and "supported_languages" in (body.agent_config or {}))):
        cfg = agent.agent_config or {}
        supported_langs = cfg.get("supported_languages", [])
        if supported_langs and not cfg.get("ivr_language_prompt"):
            new_prompt = await generate_ivr_language_prompt(db, supported_langs)
            if new_prompt:
                new_cfg = dict(agent.agent_config)
                new_cfg["ivr_language_prompt"] = new_prompt
                agent.agent_config = new_cfg
                await db.commit()
                await db.refresh(agent)
                logger.info("ivr_prompt_auto_populated", agent_id=str(agent.id))

    # Re-generate TTS audio whenever greeting or IVR prompt text changes.
    if agent.voice_enabled:
        cfg = agent.agent_config or {}
        voice_id = agent.voice_id or "alloy"
        tts_updated = False

        # Regenerate greeting audio when greeting_message changed
        if "greeting_message" in update_data or (
            "agent_config" in body.model_dump(exclude_unset=True)
            and "greeting_message" in (body.agent_config or {})
        ):
            greeting_text = cfg.get("greeting_message")
            if greeting_text:
                _validate_system_prompt(greeting_text)
                if not _has_variables(greeting_text):
                    # Resolve variables before generating audio
                    result_vars = await db.execute(select(AgentVariable).where(AgentVariable.agent_id == agent.id))
                    variables = result_vars.scalars().all()
                    resolved_greeting = resolve_agent_variables(greeting_text, agent, variables, clean=True)
                    redacted_text = redact(resolved_greeting)
                    
                    old_url = agent.agent_config.get("voice_greeting_url")
                    url = await _tts_service.generate_greeting(
                        text=redacted_text,
                        voice_id=voice_id,
                        agent_id=str(agent.id),
                    )
                    if url:
                        _delete_old_audio(old_url)
                        new_cfg = dict(agent.agent_config)
                        new_cfg["voice_greeting_url"] = url
                        agent.agent_config = new_cfg
                        tts_updated = True
                        logger.info("voice_greeting_regenerated", agent_id=str(agent.id), url=url)
                else:
                    old_url = agent.agent_config.get("voice_greeting_url")
                    if old_url:
                        _delete_old_audio(old_url)
                        new_cfg = dict(agent.agent_config)
                        new_cfg.pop("voice_greeting_url", None)
                        agent.agent_config = new_cfg
                        tts_updated = True
                        logger.info("voice_greeting_cleared", agent_id=str(agent.id))

        # Regenerate IVR audio when ivr_language_prompt changed
        if "ivr_language_prompt" in update_data or (
            "agent_config" in body.model_dump(exclude_unset=True)
            and "ivr_language_prompt" in (body.agent_config or {})
        ):
            ivr_text = cfg.get("ivr_language_prompt")
            if ivr_text:
                if not _has_variables(ivr_text):
                    # Resolve variables before generating IVR audio
                    result_vars = await db.execute(select(AgentVariable).where(AgentVariable.agent_id == agent.id))
                    variables = result_vars.scalars().all()
                    resolved_ivr = resolve_agent_variables(ivr_text, agent, variables, clean=True)
                    redacted_ivr = redact(resolved_ivr)
                    
                    old_url = agent.agent_config.get("ivr_language_url")
                    url = await _tts_service.generate_ivr_prompt(
                        text=redacted_ivr,
                        voice_id=voice_id,
                        agent_id=str(agent.id),
                    )
                    if url:
                        _delete_old_audio(old_url)
                        new_cfg = dict(agent.agent_config)
                        new_cfg["ivr_language_url"] = url
                        agent.agent_config = new_cfg
                        tts_updated = True
                        logger.info("ivr_prompt_regenerated", agent_id=str(agent.id), url=url)
                else:
                    old_url = agent.agent_config.get("ivr_language_url")
                    if old_url:
                        _delete_old_audio(old_url)
                        new_cfg = dict(agent.agent_config)
                        new_cfg.pop("ivr_language_url", None)
                        agent.agent_config = new_cfg
                        tts_updated = True
                        logger.info("ivr_prompt_cleared", agent_id=str(agent.id))

        # Regenerate mandatory opening audio when languages or voice changes
        if any(f in update_data for f in ["language", "supported_languages", "voice_id"]) or (
            "agent_config" in body.model_dump(exclude_unset=True)
            and any(f in (body.agent_config or {}) for f in ["supported_languages"])
        ):
            supported_langs = cfg.get("supported_languages", [])
            custom_greeting = (agent.agent_config or {}).get("greeting_message")
            opening_text = await generate_multilingual_greeting(db, agent.language, supported_langs, custom_greeting=custom_greeting)
            if opening_text:
                if not _has_variables(opening_text):
                    # Resolve variables in mandatory opening
                    result_vars = await db.execute(select(AgentVariable).where(AgentVariable.agent_id == agent.id))
                    variables = result_vars.scalars().all()
                    resolved_opening = resolve_agent_variables(opening_text, agent, variables, clean=True)
                    redacted_opening = redact(resolved_opening)
                    
                    old_url = agent.agent_config.get("opening_audio_url")
                    url = await _tts_service.generate_opening(
                        text=redacted_opening,
                        voice_id=voice_id,
                        agent_id=str(agent.id),
                    )
                    if url:
                        _delete_old_audio(old_url)
                        new_cfg = dict(agent.agent_config)
                        new_cfg["opening_audio_url"] = url
                        agent.agent_config = new_cfg
                        tts_updated = True
                        logger.info("voice_opening_regenerated", agent_id=str(agent.id), url=url)
                else:
                    old_url = agent.agent_config.get("opening_audio_url")
                    if old_url:
                        _delete_old_audio(old_url)
                        new_cfg = dict(agent.agent_config)
                        new_cfg.pop("opening_audio_url", None)
                        agent.agent_config = new_cfg
                        tts_updated = True
                        logger.info("voice_opening_cleared", agent_id=str(agent.id))

    logger.info(
        "agent_updated",
        agent_id=str(agent.id),
        tenant_id=tenant_id,
        actor_email=request.headers.get("X-Actor-Email", "unknown"),
        updated_fields=list(update_data.keys()),
    )
    return await _agent_to_response(agent, db)


@router.post("/{agent_id}/generate-greeting-audio", response_model=AgentResponse)
async def generate_agent_greeting_audio(
    agent_id: str,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
):
    """Manually trigger TTS generation for the agent's current greeting_message."""
    tenant_id = _tenant_id(request)
    
    # Apply isolation (CRIT-005)
    raid = _restricted_agent_id(request)
    if raid and uuid.UUID(agent_id) != raid:
        raise HTTPException(status_code=404, detail="Agent not found.")

    result = await db.execute(
        select(Agent).where(
            Agent.id == uuid.UUID(agent_id),
            Agent.tenant_id == uuid.UUID(tenant_id),
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found.")

    cfg = agent.agent_config or {}
    greeting_text = cfg.get("greeting_message")
    if not greeting_text:
        raise HTTPException(status_code=400, detail="No greeting message configured.")

    voice_id = agent.voice_id or "alloy"
    
    _validate_system_prompt(greeting_text)
    
    if _has_variables(greeting_text):
        raise HTTPException(status_code=400, detail="Cannot manually generate audio for a greeting with session variables.")

    # Resolve variables for audio
    result_vars = await db.execute(select(AgentVariable).where(AgentVariable.agent_id == agent.id))
    variables = result_vars.scalars().all()
    resolved_text = resolve_agent_variables(greeting_text, agent, variables, clean=True)
    redacted_text = redact(resolved_text)

    old_url = agent.agent_config.get("voice_greeting_url")
    url = await _tts_service.generate_greeting(
        text=redacted_text,
        voice_id=voice_id,
        agent_id=str(agent.id),
    )
    if not url:
        raise HTTPException(status_code=500, detail="TTS generation failed.")
        
    _delete_old_audio(old_url)

    new_cfg = dict(agent.agent_config)
    new_cfg["voice_greeting_url"] = url
    agent.agent_config = new_cfg
    await db.commit()
    await db.refresh(agent)
    
    logger.info("voice_greeting_manually_generated", agent_id=agent_id, url=url)
    return await _agent_to_response(agent, db)


@router.post("/{agent_id}/generate-ivr-audio", response_model=AgentResponse)
async def generate_agent_ivr_audio(
    agent_id: str,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
):
    """Manually trigger TTS generation for the agent's current ivr_language_prompt."""
    tenant_id = _tenant_id(request)
    
    # Apply isolation (CRIT-005)
    raid = _restricted_agent_id(request)
    if raid and uuid.UUID(agent_id) != raid:
        raise HTTPException(status_code=404, detail="Agent not found.")

    result = await db.execute(
        select(Agent).where(
            Agent.id == uuid.UUID(agent_id),
            Agent.tenant_id == uuid.UUID(tenant_id),
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found.")

    cfg = agent.agent_config or {}
    ivr_text = cfg.get("ivr_language_prompt")
    if not ivr_text:
        raise HTTPException(status_code=400, detail="No IVR prompt configured.")

    voice_id = agent.voice_id or "alloy"
    
    if _has_variables(ivr_text):
        raise HTTPException(status_code=400, detail="Cannot manually generate audio for an IVR prompt with session variables.")

    # Resolve variables for audio
    result_vars = await db.execute(select(AgentVariable).where(AgentVariable.agent_id == agent.id))
    variables = result_vars.scalars().all()
    resolved_text = resolve_agent_variables(ivr_text, agent, variables, clean=True)
    redacted_text = redact(resolved_text)

    old_url = agent.agent_config.get("ivr_language_url")
    url = await _tts_service.generate_ivr_prompt(
        text=redacted_text,
        voice_id=voice_id,
        agent_id=str(agent.id),
    )
    if not url:
        raise HTTPException(status_code=500, detail="TTS generation failed.")
        
    _delete_old_audio(old_url)

    new_cfg = dict(agent.agent_config)
    new_cfg["ivr_language_url"] = url
    agent.agent_config = new_cfg
    await db.commit()
    await db.refresh(agent)
    
    logger.info("ivr_prompt_manually_generated", agent_id=agent_id, url=url)
    return await _agent_to_response(agent, db)



# ---------------------------------------------------------------------------
# IVR DTMF Menu  (Phase 4: Pre-LLM Static DTMF Routing)
# ---------------------------------------------------------------------------

@router.get("/{agent_id}/ivr-dtmf-menu")
async def get_ivr_dtmf_menu(
    agent_id: str,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
):
    """Retrieve the DTMF menu configuration for this agent."""
    tenant_id = _tenant_id(request)
    raid = _restricted_agent_id(request)
    if raid and uuid.UUID(agent_id) != raid:
        raise HTTPException(status_code=404, detail="Agent not found.")

    result = await db.execute(
        select(Agent).where(
            Agent.id == uuid.UUID(agent_id),
            Agent.tenant_id == uuid.UUID(tenant_id),
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found.")

    menu = (agent.agent_config or {}).get("ivr_dtmf_menu", {
        "timeout_seconds": 10,
        "max_retries": 3,
        "entries": [],
    })
    return {"ivr_dtmf_menu": menu}


@router.patch("/{agent_id}/ivr-dtmf-menu")
async def update_ivr_dtmf_menu(
    agent_id: str,
    request: Request,
    body: dict,
    db: AsyncSession = Depends(get_tenant_db),
):
    """Save the DTMF menu configuration for this agent."""
    tenant_id = _tenant_id(request)
    raid = _restricted_agent_id(request)
    if raid and uuid.UUID(agent_id) != raid:
        raise HTTPException(status_code=404, detail="Agent not found.")

    result = await db.execute(
        select(Agent).where(
            Agent.id == uuid.UUID(agent_id),
            Agent.tenant_id == uuid.UUID(tenant_id),
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found.")

    menu = body.get("ivr_dtmf_menu", body)

    # Validate basic structure
    if not isinstance(menu.get("entries", []), list):
        raise HTTPException(status_code=400, detail="ivr_dtmf_menu.entries must be a list.")

    valid_actions = {"play_audio", "proceed_to_agent", "end_call", "repeat_menu"}
    for entry in menu.get("entries", []):
        if entry.get("action") not in valid_actions:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid action '{entry.get('action')}'. Must be one of: {valid_actions}",
            )

    new_cfg = dict(agent.agent_config or {})
    new_cfg["ivr_dtmf_menu"] = menu
    agent.agent_config = new_cfg
    flag_modified(agent, "agent_config")
    await db.commit()
    await db.refresh(agent)

    logger.info("ivr_dtmf_menu_updated", agent_id=agent_id, entries=len(menu.get("entries", [])))
    return {"ivr_dtmf_menu": new_cfg["ivr_dtmf_menu"]}


@router.post("/{agent_id}/ivr-dtmf-menu/{digit}/generate-audio")
async def generate_dtmf_entry_audio(
    agent_id: str,
    digit: str,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
):
    """Generate TTS audio for a specific DTMF menu entry identified by its digit key."""
    tenant_id = _tenant_id(request)
    raid = _restricted_agent_id(request)
    if raid and uuid.UUID(agent_id) != raid:
        raise HTTPException(status_code=404, detail="Agent not found.")

    result = await db.execute(
        select(Agent).where(
            Agent.id == uuid.UUID(agent_id),
            Agent.tenant_id == uuid.UUID(tenant_id),
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found.")

    cfg = agent.agent_config or {}
    menu = cfg.get("ivr_dtmf_menu", {})
    entries = menu.get("entries", [])

    # Find the entry for this digit
    entry = next((e for e in entries if e.get("digit") == digit), None)
    if not entry:
        raise HTTPException(status_code=404, detail=f"No DTMF entry found for digit '{digit}'.")

    audio_text = entry.get("audio_text", "").strip()
    if not audio_text:
        raise HTTPException(status_code=400, detail="No audio_text configured for this entry.")

    if _has_variables(audio_text):
        raise HTTPException(status_code=400, detail="Cannot pre-generate audio for text containing session variables.")

    voice_id = agent.voice_id or "alloy"

    # Resolve agent variables
    result_vars = await db.execute(select(AgentVariable).where(AgentVariable.agent_id == agent.id))
    variables = result_vars.scalars().all()
    resolved_text = resolve_agent_variables(audio_text, agent, variables, clean=True)
    redacted_text = redact(resolved_text)

    # Delete old audio file for this digit if it exists
    old_url = entry.get("audio_url")
    _delete_old_audio(old_url)

    url = await _tts_service.generate_ivr_prompt(
        text=redacted_text,
        voice_id=voice_id,
        agent_id=f"{str(agent.id)}_dtmf_{digit}",
    )
    if not url:
        raise HTTPException(status_code=500, detail="TTS generation failed.")

    # Persist the audio_url back into the DTMF menu entry
    new_cfg = dict(cfg)
    new_menu = dict(menu)
    new_entries = [dict(e) for e in entries]
    for e in new_entries:
        if e.get("digit") == digit:
            e["audio_url"] = url
    new_menu["entries"] = new_entries
    new_cfg["ivr_dtmf_menu"] = new_menu
    agent.agent_config = new_cfg
    flag_modified(agent, "agent_config")
    await db.commit()
    await db.refresh(agent)

    logger.info("dtmf_entry_audio_generated", agent_id=agent_id, digit=digit, url=url)
    return {"digit": digit, "audio_url": url, "ivr_dtmf_menu": new_menu}


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    agent_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    _role: str = require_forwarded_role("admin"),
    db: AsyncSession = Depends(get_tenant_db),
    tenant_id: str = Depends(get_current_tenant),
):
    """Deactivate an agent (transition to ARCHIVED state) and purge knowledge."""
    from shared.orchestration.agent_lifecycle import transition_agent, AgentLifecycleError

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
    
    # Phase 8: Proactive knowledge purge
    background_tasks.add_task(_background_purge_agent_knowledge, agent_id, tenant_id)


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
    from shared.orchestration.agent_lifecycle import transition_agent, AgentLifecycleError

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
    
    # Apply isolation (CRIT-005)
    raid = _restricted_agent_id(request)
    if raid and uuid.UUID(agent_id) != raid:
        raise HTTPException(status_code=404, detail="Agent not found.")

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
    new_cfg = dict(agent.agent_config or {})
    new_cfg["voice_greeting_url"] = url
    agent.agent_config = new_cfg
    flag_modified(agent, "agent_config")
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
    
    # Apply isolation (CRIT-005)
    raid = _restricted_agent_id(request)
    if raid and uuid.UUID(agent_id) != raid:
        raise HTTPException(status_code=404, detail="Agent not found.")

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
    existing_url = (agent.agent_config or {}).get("voice_greeting_url")
    if existing_url:
        filename = Path(existing_url).name
        filepath = _GREETING_AUDIO_DIR / filename
        if filepath.exists():
            filepath.unlink(missing_ok=True)
    new_cfg = dict(agent.agent_config or {})
    new_cfg.pop("voice_greeting_url", None)
    agent.agent_config = new_cfg
    flag_modified(agent, "agent_config")
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
    
    # Apply isolation (CRIT-005)
    raid = _restricted_agent_id(request)
    if raid and uuid.UUID(agent_id) != raid:
        raise HTTPException(status_code=404, detail="Agent not found.")

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
