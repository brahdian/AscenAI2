import uuid
import json
from typing import List, Dict, Any, Optional
import structlog

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, Request
from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified
from pydantic import BaseModel

# AgentTemplate rows are GLOBAL seed data — they have no tenant_id column and
# must be read with a session that bypasses RLS (get_db_no_rls).
# AgentTemplateInstance rows ARE tenant-scoped and use get_tenant_db.
from app.core.database import get_db, get_db_no_rls, AsyncSessionLocal
from app.core.config import settings
from app.core.security import get_tenant_db, get_current_tenant, get_actor_info
from app.core.rate_limiter import RateLimiter
from app.models.agent import (
    Agent, AgentPlaybook, AgentGuardrails, AgentDocument,
    AgentGuardrailChangeRequest, GuardrailEvent
)
from app.models.variable import AgentVariable
from app.models.template import (
    AgentTemplate,
    TemplateVersion,
    AgentTemplateInstance,
    TemplateVariable,
    TemplateTool,
)
import app.services.pii_service as pii_service
from app.api.v1.agents import _validate_system_prompt
from app.schemas.template import AgentTemplateSchema, TemplateInstantiationRequest, AgentTemplateInstanceSchema

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["Templates"])


def _restricted_agent_id(request: Request) -> uuid.UUID | None:
    """Extract optional agent restriction passed by the API Gateway proxy."""
    raid = request.headers.get("X-Restricted-Agent-ID")
    if raid:
        try:
            return uuid.UUID(raid)
        except ValueError:
            return None
    return None

# IMPORTANT: Routes with literal path segments (e.g. /instances/...) MUST be
# registered BEFORE parameterized routes (e.g. /{template_id}) so FastAPI
# does not greedily match the literal segment as a parameter value.

# ---------------------------------------------------------------------------
# Instance endpoints — registered first to prevent shadowing by /{template_id}
# ---------------------------------------------------------------------------

@router.get("/instances/by-agent/{agent_id}", response_model=Optional[AgentTemplateInstanceSchema])
async def get_instance_by_agent(
    agent_id: str,
    request: Request,
    tenant=Depends(get_current_tenant),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Retrieve the template instance applied to an agent, if any."""
    # Apply isolation (CRIT-005)
    raid = _restricted_agent_id(request)
    if raid and uuid.UUID(agent_id) != raid:
        return None

    try:
        a_uuid = uuid.UUID(agent_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID for agent_id")

    result = await db.execute(
        select(AgentTemplateInstance)
        .where(
            AgentTemplateInstance.agent_id == a_uuid,
            AgentTemplateInstance.tenant_id == tenant
        )
        .order_by(AgentTemplateInstance.created_at.desc())
        .limit(1)
    )
    instance = result.scalar_one_or_none()
    
    # Return 200 OK with null if not found, rather than 404,
    # as not all agents are expected to have templates.
    return instance


class InstanceUpdateRequest(BaseModel):
    variable_values: Dict[str, Any]

@router.patch("/instances/{instance_id}", response_model=AgentTemplateInstanceSchema)
async def update_instance(
    instance_id: str,
    body: InstanceUpdateRequest,
    request: Request,
    tenant=Depends(get_current_tenant),
    db: AsyncSession = Depends(get_tenant_db),
    actor_info: Dict[str, Any] = Depends(get_actor_info)
):
    """Update variable values of a template instance and re-apply to the agent."""
    try:
        i_uuid = uuid.UUID(instance_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID for instance_id")

    # Fetch instance along with related template version
    query = select(AgentTemplateInstance).where(
        AgentTemplateInstance.id == i_uuid,
        AgentTemplateInstance.tenant_id == tenant
    ).options(selectinload(AgentTemplateInstance.version))
    
    # Apply isolation (CRIT-005)
    raid = _restricted_agent_id(request)
    if raid:
        query = query.where(AgentTemplateInstance.agent_id == raid)

    result = await db.execute(query)
    instance = result.scalar_one_or_none()
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")

    # Update variable values — use a new dict so SQLAlchemy detects the assignment
    current_vars = dict(instance.variable_values or {})
    current_vars.update(body.variable_values)
    instance.variable_values = current_vars

    # Re-apply to agent prompt
    agent_res = await db.execute(select(Agent).where(Agent.id == instance.agent_id))
    agent = agent_res.scalar_one_or_none()

    version = instance.version

    # Fetch variable definitions from template version to identify secrets.
    # Reuse the existing RLS-scoped `db` session — no secondary connection needed.
    from app.models.template import TemplateVariable
    vd_res = await db.execute(
        select(TemplateVariable).where(TemplateVariable.template_id == version.template_id)
    )
    secrets = {tv.key for tv in vd_res.scalars().all() if tv.is_secret}

    def _render_str(text: str) -> str:
        # PII Protection: do NOT render variables that are marked as sensitive
        # in logs or intermediate steps. Use a safer multi-pass substitution.
        if not text:
            return ""
        rendered = text
        for k, v in instance.variable_values.items():
            # FIX-04: Never render secrets into the static prompt
            val_str = "[REDACTED]" if k in secrets else str(v)
            rendered = rendered.replace("{{" + k + "}}", val_str)
            rendered = rendered.replace("{" + k + "}", val_str)
            rendered = rendered.replace(f"$[vars:{k}]", val_str)
            rendered = rendered.replace(f"$vars:{k}", val_str)
        return rendered

    if agent and version and version.system_prompt_template:
        agent.system_prompt = _render_str(version.system_prompt_template)

    # Re-render voice greeting if it exists in config
    if agent and agent.agent_config and "greeting_message" in agent.agent_config:
        # We need the original greeting template to re-render. 
        # For simplicity, we only re-render if we can infer it or if it's stored.
        # Template-sourced agents store the version greeting.
        if version and version.voice_greeting:
            agent.agent_config["greeting_message"] = _render_str(version.voice_greeting)

    # Re-render all playbook config fields so {{variables}} stay current
    if agent:
        pb_res = await db.execute(
            select(AgentPlaybook).where(AgentPlaybook.agent_id == agent.id)
        )
        for pb in pb_res.scalars().all():
            if not pb.config:
                continue
            # Re-render entire config blob via JSON round-trip
            try:
                # Only re-render if it's a template-sourced playbook or matches simple patterns
                rendered_cfg = json.loads(_render_str(json.dumps(pb.config)))
                pb.config = rendered_cfg
                flag_modified(pb, "config")
            except Exception:
                pass  # leave unchanged if serialisation fails

    # Zenith Forensics: Capture the actor signature for every mutation
    logger.info(
        "template_instance_updated",
        instance_id=str(instance.id),
        agent_id=str(agent.id) if agent else None,
        actor_email=actor_info.get("actor_email") if actor_info else "unknown",
        is_support_access=actor_info.get("is_support_access") if actor_info else False,
        trace_id=actor_info.get("trace_id") if actor_info else "unknown",
        # Zenith Privacy: Redact sensitive variable values in logs
        variable_keys=list(body.variable_values.keys())
    )
    await db.commit()
    await db.refresh(instance)
    return instance


# ---------------------------------------------------------------------------
# Validation Helpers
# ---------------------------------------------------------------------------

def _validate_variables(var_defs: Dict[str, dict], provided_vars: Dict[str, Any]):
    """Ensure all required variables are present and types are valid."""
    errors = []
    for key, meta in var_defs.items():
        val = provided_vars.get(key)
        
        # Check required
        if meta.get("required") and (val is None or val == ""):
            errors.append(f"Variable '{key}' ({meta.get('label')}) is required.")
            continue
            
        if val is None:
            continue
            
        # Basic type checking
        vtype = meta.get("type", "string")
        if vtype == "number" and not isinstance(val, (int, float, str)):
            # Handle string-encoded numbers from JSON
            try: float(val)
            except: errors.append(f"Variable '{key}' must be a number.")
        elif vtype == "boolean" and not isinstance(val, (bool, str)):
             if str(val).lower() not in ("true", "false", "1", "0"):
                errors.append(f"Variable '{key}' must be a boolean.")
                
    if errors:
        raise HTTPException(status_code=422, detail={"message": "Validation failed", "errors": errors})


def _validate_tool_configs(tools_data: List[dict], provided_configs: Dict[str, Any]):
    """Validate tool configurations against the template's required schema."""
    # Note: In a real prod system, use jsonschema.validate here.
    # For now, we perform basic presence checks for required keys.
    errors = []
    for tool in tools_data:
        tname = tool["tool_name"]
        schema = tool.get("required_config_schema", {})
        if not schema:
            continue
            
        config = provided_configs.get(tname, {})
        required_keys = schema.get("required", [])
        for k in required_keys:
            if k not in config or config[k] == "":
                errors.append(f"Tool '{tname}' requires configuration field '{k}'.")
                
    if errors:
        raise HTTPException(status_code=422, detail={"message": "Tool configuration failed", "errors": errors})



# ---------------------------------------------------------------------------
# Template catalog endpoints — use get_db_no_rls because AgentTemplate has
# NO tenant_id column (seed/global data). Reading with a tenant-scoped session
# would inject SET LOCAL which does nothing, but any RLS on the table would
# block all rows if the policy requires tenant_id = current_tenant_id().
# ---------------------------------------------------------------------------

@router.get("", response_model=List[AgentTemplateSchema])
async def list_templates(
    tenant=Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db_no_rls)
):
    """List all active agent templates with their versions and variables."""
    result = await db.execute(
        select(AgentTemplate)
        .where(AgentTemplate.is_active == True)
        .options(
            selectinload(AgentTemplate.variables),
            selectinload(AgentTemplate.versions).selectinload(TemplateVersion.playbooks),
            selectinload(AgentTemplate.versions).selectinload(TemplateVersion.tools),
        )
        # Zenith Determinism: Mandatory multi-column deterministic sorting
        .order_by(AgentTemplate.created_at.desc(), AgentTemplate.id.desc())
    )
    return list(result.scalars().unique().all())


@router.get("/{template_id}", response_model=AgentTemplateSchema)
async def get_template(
    template_id: str,
    tenant=Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db_no_rls)
):
    """Retrieve a single agent template with its nested configuration."""
    try:
        t_uuid = uuid.UUID(template_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID for template_id")
        
    result = await db.execute(
        select(AgentTemplate)
        .where(AgentTemplate.id == t_uuid, AgentTemplate.is_active == True)
        .options(
            selectinload(AgentTemplate.variables),
            selectinload(AgentTemplate.versions).selectinload(TemplateVersion.playbooks),
            selectinload(AgentTemplate.versions).selectinload(TemplateVersion.tools),
        )
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


@router.post("/{template_id}/instantiate", response_model=dict)
async def instantiate_template(
    template_id: str,
    body: TemplateInstantiationRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    tenant: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_tenant_db),
    actor_info: Dict[str, Any] = Depends(get_actor_info),
):
    """
    Instantiate a template onto an existing agent.
    Applies the template version's rules, copying playbooks and setting prompts based on variable values.
    Template catalog is read without RLS; instance is written into the tenant's RLS context.
    """
    # Zenith Resilience: Apply Redis-backed rate limiting (5 per minute per tenant)
    limiter = RateLimiter(request.app.state.redis)
    if not await limiter.is_allowed(f"tpl_inst:{tenant}", limit=5, window_seconds=60):
        logger.warning("rate_limit_exceeded", tenant_id=tenant, action="template_instantiation")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please wait before instantiating another template."
        )

    try:
        t_uuid = uuid.UUID(template_id)
        v_uuid = uuid.UUID(body.template_version_id)
        a_uuid = uuid.UUID(body.agent_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format in request")

    # Verify agent exists for tenant (uses get_tenant_db — RLS guards this)
    query = select(Agent).where(Agent.id == a_uuid, Agent.tenant_id == uuid.UUID(tenant))
    
    # Apply isolation (CRIT-005)
    raid = _restricted_agent_id(request)
    if raid:
        if a_uuid != raid:
            raise HTTPException(status_code=403, detail="Access denied to this agent.")
        query = query.where(Agent.id == raid)

    agent_res = await db.execute(query)
    agent = agent_res.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    return await process_template_instantiation(
        t_uuid=t_uuid,
        v_uuid=v_uuid,
        agent=agent,
        tenant=tenant,
        db=db,
        request=request,
        background_tasks=background_tasks,
        variable_values=body.variable_values,
        tool_configs=body.tool_configs,
        actor_info=actor_info,
    )

async def process_template_instantiation(
    t_uuid: uuid.UUID,
    v_uuid: uuid.UUID,
    agent: Agent,
    tenant: str,
    db: AsyncSession,
    request: Request,
    background_tasks: BackgroundTasks,
    variable_values: dict,
    tool_configs: dict,
    actor_info: dict,
) -> dict:
    """Internal utility to instantiate a template onto an agent."""
    # -----------------------------------------------------------------------
    # Retrieve template version from the global catalog using a NO-RLS session.
    # IMPORTANT: Extract ALL data we need into plain Python objects INSIDE the
    # `async with` block, before the session closes. Accessing ORM relationship
    # attributes on detached objects (after session close) raises
    # DetachedInstanceError, which would silently skip playbook creation.
    # -----------------------------------------------------------------------
    system_prompt_template: str | None = None
    template_voice_greeting: str | None = None
    playbooks_data: list[dict] = []
    tools_data: list[dict] = []
    var_defs: dict[str, dict] = {}   # keyed by variable key, holds label/type
    
    # Security & Compliance payloads
    compliance_payload: dict | None = None
    guardrails_payload: dict | None = None
    emergency_protocols_payload: dict | None = None

    async with AsyncSessionLocal() as catalog_db:
        version_res = await catalog_db.execute(
            select(TemplateVersion)
            .where(TemplateVersion.id == v_uuid, TemplateVersion.template_id == t_uuid)
            .options(
                selectinload(TemplateVersion.playbooks),
                selectinload(TemplateVersion.tools),
            )
        )
        version = version_res.scalar_one_or_none()

        if not version:
            raise HTTPException(status_code=404, detail="Template version not found")

        # Snapshot everything into plain Python structures while session is open
        system_prompt_template = version.system_prompt_template
        template_voice_greeting = version.voice_greeting
        version_id = version.id
        
        compliance_payload = dict(version.compliance) if version.compliance else None
        guardrails_payload = dict(version.guardrails) if version.guardrails else None
        emergency_protocols_payload = dict(version.emergency_protocols) if version.emergency_protocols else None

        # Snapshot template variable definitions for use as AgentVariable labels
        from app.models.template import TemplateVariable
        tvar_res = await catalog_db.execute(
            select(TemplateVariable).where(TemplateVariable.template_id == t_uuid)
        )
        for tvar in tvar_res.scalars().all():
            var_defs[tvar.key] = {
                "label": tvar.label,
                "type": tvar.type,
                "required": tvar.is_required,
                "is_secret": tvar.is_secret,
                "default": tvar.default_value.get("value") if isinstance(tvar.default_value, dict) else tvar.default_value
            }

        for pbook in version.playbooks:
            playbook_config = dict(pbook.config) if pbook.config else {}
            playbooks_data.append({
                "name": pbook.name,
                "description": pbook.description,
                "trigger_condition": dict(pbook.trigger_condition) if pbook.trigger_condition else {},
                "tone": playbook_config.get("tone", "professional"),
                "dos": playbook_config.get("dos", []),
                "donts": playbook_config.get("donts", []),
                "scenarios": playbook_config.get("scenarios", []),
                "out_of_scope_response": playbook_config.get("out_of_scope_response"),
                "fallback_response": playbook_config.get("fallback_response"),
                "custom_escalation_message": playbook_config.get("custom_escalation_message"),
                "config": playbook_config,
            })

        for vt in version.tools:
            tools_data.append({
                "tool_name": vt.tool_name,
                "required_config_schema": dict(vt.required_config_schema) if vt.required_config_schema else {},
            })
    # catalog_db is now safely closed — we work only with plain dicts from here.

    # -----------------------------------------------------------------------
    # Validation Phase
    # -----------------------------------------------------------------------
    _validate_variables(var_defs, variable_values)
    _validate_tool_configs(tools_data, tool_configs)

    logger.info(
        "template_instantiate_start",
        template_id=str(t_uuid),
        version_id=str(version_id),
        playbook_count=len(playbooks_data),
        tool_count=len(tools_data),
        actor_email=actor_info["actor_email"],
        is_support_access=actor_info["is_support_access"],
        trace_id=actor_info["trace_id"],
    )

    # -----------------------------------------------------------------------
    # Helper: substitute {{key}} and {key} template variables in a string
    # -----------------------------------------------------------------------
    def _render(text: str) -> str:
        if not text:
            return ""
        rendered = text
        for k, v in variable_values.items():
            # FIX-04: Never render secrets into the static prompt
            is_secret = var_defs.get(k, {}).get("is_secret", False)
            val_str = "[REDACTED]" if is_secret else str(v)
            
            rendered = rendered.replace("{{" + k + "}}", val_str)
            rendered = rendered.replace("{" + k + "}", val_str)
            rendered = rendered.replace(f"$[vars:{k}]", val_str)
            rendered = rendered.replace(f"$vars:{k}", val_str)
        return rendered

    # Update agent system prompt by substituting variable_values
    if system_prompt_template:
        rendered_prompt = _render(system_prompt_template)
        # Phase 9: Protect against variable-based jailbreak or role injection
        _validate_system_prompt(rendered_prompt)
        agent.system_prompt = rendered_prompt
    
    # Update voice greeting if provided by template
    if template_voice_greeting:
        if agent.agent_config is None:
            agent.agent_config = {}
        rendered_greeting = _render(template_voice_greeting)
        # Phase 9: Protect against variable-based jailbreak in greetings
        _validate_system_prompt(rendered_greeting)
        agent.agent_config["greeting_message"] = rendered_greeting

    # Add tool configurations
    if tools_data:
        agent_cfg = agent.agent_config or {}
        agent_tools = list(agent_cfg.get("tools", []) or [])
        for vt in tools_data:
            tool_cfg = tool_configs.get(vt["tool_name"], {})
            agent_tools.append({
                "name": vt["tool_name"],
                "config": tool_cfg,
            })
        agent.agent_config["tools"] = agent_tools
    
    # Apply Compliance & Emergency Protocols to AgentConfig
    if compliance_payload or emergency_protocols_payload:
        if agent.agent_config is None:
            agent.agent_config = {}
        if compliance_payload:
            agent.agent_config["compliance"] = compliance_payload
        if emergency_protocols_payload:
            agent.agent_config["emergency_protocols"] = emergency_protocols_payload
        flag_modified(agent, "agent_config")

    # -----------------------------------------------------------------------
    # Delete the auto-generated default playbooks so template ones replace them.
    # ONLY delete playbooks that are marked as being from a template.
    # -----------------------------------------------------------------------
    if playbooks_data:
        # Check if the agent is brand new (status=DRAFT) — if so, we can clear everything.
        # Otherwise, only clear playbooks marked as template-sourced.
        if agent.status == "DRAFT":
            await db.execute(
                delete(AgentPlaybook).where(AgentPlaybook.agent_id == agent.id)
            )
        else:
            await db.execute(
                delete(AgentPlaybook).where(
                    AgentPlaybook.agent_id == agent.id,
                    AgentPlaybook.is_from_template == True
                )
            )

    # Copy template playbooks as AgentPlaybook rows
    for pbook in playbooks_data:
        trigger_condition = pbook.get("trigger_condition", {})
        triggers = trigger_condition.get("keywords", []) if isinstance(trigger_condition, dict) else []
        if isinstance(trigger_condition, dict) and "intent" in trigger_condition:
            triggers.append(trigger_condition["intent"])

        instructions = _render(pbook.get("instructions") or pbook.get("config", {}).get("instructions") or "")

        description = _render(pbook.get("description") or "")
        tone = _render(pbook.get("tone") or "professional")
        dos = [_render(str(item)) for item in (pbook.get("dos") or [])]
        donts = [_render(str(item)) for item in (pbook.get("donts") or [])]
        scenarios_raw = pbook.get("scenarios") or pbook.get("config", {}).get("scenarios") or []
        rendered_scenarios = [
            {
                "trigger": _render(s.get("trigger", "")),
                "response": _render(s.get("response") or s.get("ai") or ""),
            }
            for s in scenarios_raw
        ]

        # Explicitly render secondary fields
        out_of_scope_response = _render(pbook.get("out_of_scope_response") or pbook.get("config", {}).get("out_of_scope_response") or "")
        fallback_response = _render(pbook.get("fallback_response") or pbook.get("config", {}).get("fallback_response") or "")
        custom_escalation_message = _render(pbook.get("custom_escalation_message") or pbook.get("config", {}).get("custom_escalation_message") or "")
        tools = pbook.get("tools") or pbook.get("config", {}).get("tools") or []
        variables = pbook.get("variables") or pbook.get("config", {}).get("variables") or []

        # Recursive Replication: Copy all keys from the template playbook config
        # ensuring tone, dos, donts, scenarios, tools, variables, etc. are preserved.
        pb_config = dict(pbook.get("config", {}))
        
        # Render specific fields that might contain {{variables}}
        rendered_config = {}
        for k, v in pb_config.items():
            if isinstance(v, str):
                rendered_config[k] = _render(v)
            elif isinstance(v, list) and k in ("dos", "donts", "scenarios"):
                rendered_config[k] = []
                for item in v:
                    if isinstance(item, str):
                        rendered_config[k].append(_render(item))
                    elif isinstance(item, dict):
                        rendered_config[k].append({rk: (_render(rv) if isinstance(rv, str) else rv) for rk, rv in item.items()})
                    else:
                        rendered_config[k].append(item)
            else:
                rendered_config[k] = v

        # Explicitly ensure these core fields are present and rendered
        rendered_config["instructions"] = instructions
        rendered_config["tone"] = tone
        rendered_config["dos"] = dos
        rendered_config["donts"] = donts
        rendered_config["scenarios"] = rendered_scenarios
        rendered_config["out_of_scope_response"] = out_of_scope_response or None
        rendered_config["fallback_response"] = fallback_response or None
        rendered_config["custom_escalation_message"] = custom_escalation_message or None
        rendered_config["tools"] = tools
        rendered_config["variables"] = variables



        playbook = AgentPlaybook(
            agent_id=agent.id,
            tenant_id=uuid.UUID(tenant),
            name=pbook["name"],
            description=description or None,
            intent_triggers=triggers,
            is_default=False,
            is_from_template=True,
            source_template_id=t_uuid,
            config=rendered_config,
            is_active=True,
        )
        db.add(playbook)
        logger.info("template_playbook_added", name=pbook["name"], agent_id=str(agent.id))

    # Update existing Guardrails, or create if missing
    gr_res = await db.execute(select(AgentGuardrails).where(AgentGuardrails.agent_id == agent.id))
    guardrails = gr_res.scalar_one_or_none()
    
    # Merge template-defined guardrails with system defaults
    merged_gr_config = {
        "pii_redaction": True,
        "profanity_filter": True,
        "pii_pseudonymization": True,
        "is_active": True,
    }
    if guardrails_payload:
        merged_gr_config.update(guardrails_payload)

    if guardrails:
        guardrails.config.update(merged_gr_config)
        guardrails.is_active = True
        flag_modified(guardrails, "config")
    else:
        guardrails = AgentGuardrails(
            agent_id=agent.id,
            tenant_id=uuid.UUID(tenant),
            config=merged_gr_config,
            is_active=True,
        )
        db.add(guardrails)
    
    # Create an audit trail for the guardrail change
    change_req = AgentGuardrailChangeRequest(
        tenant_id=uuid.UUID(tenant),
        guardrail_id=str(guardrails.id) if guardrails.id else "NEW",
        proposed_rule=json.dumps(merged_gr_config),
        reason=f"Inherited from template {str(t_uuid)} version {version_id}",
        status="approved"
    )
    db.add(change_req)

    # Record the template instance (this proves instantiation succeeded)
    instance = AgentTemplateInstance(
        tenant_id=uuid.UUID(tenant),
        agent_id=agent.id,
        template_version_id=version_id,
        variable_values=variable_values,
        tool_configs=tool_configs,
    )
    db.add(instance)

    # ------------------------------------------------------------------
    # Sync template variable_values → agent_variables table so they are
    # visible and editable on the Variables page in the UI.
    # Skip internal routing keys that have no meaning as runtime variables.
    # var_defs was populated inside the catalog_db block above.
    # ------------------------------------------------------------------
    _SKIP_VARIABLE_KEYS = {"business_type", "language"}

    # Delete any existing template-sourced variables before re-seeding so
    # re-instantiation (e.g., after variable edit) doesn't create duplicates.
    existing_vars_res = await db.execute(
        select(AgentVariable).where(AgentVariable.agent_id == agent.id)
    )
    existing_var_names = {v.name: v for v in existing_vars_res.scalars().all()}

    # Merge keys from both variable_values (user-supplied) and var_defs (template
    # defaults) so variables are always seeded even when the user skipped the form.
    all_var_keys = set(variable_values.keys()) | set(var_defs.keys())
    for key in all_var_keys:
        if key in _SKIP_VARIABLE_KEYS or key.lower() == "faqs":
            continue  # FAQs become documents; routing keys are noise

        # Prefer user-supplied value; fall back to template default
        tvar_meta = var_defs.get(key, {})
        value = variable_values.get(key, tvar_meta.get("default", ""))
        is_secret = tvar_meta.get("is_secret", False)

        # Infer data type
        if isinstance(value, bool):
            dtype = "boolean"
        elif isinstance(value, (int, float)):
            dtype = "number"
        elif isinstance(value, (dict, list)):
            dtype = "object"
        else:
            dtype = "string"

        # Use the template definition label as description if available
        description = tvar_meta.get("label") or key.replace("_", " ").title()

        if key in existing_var_names:
            # Update existing — preserve scope/secret settings
            ev = existing_var_names[key]
            ev.default_value = value
            ev.description = description
            ev.data_type = dtype
            ev.is_secret = is_secret # Sync secret status from template
        else:
            av = AgentVariable(
                id=uuid.uuid4(),
                agent_id=agent.id,
                tenant_id=uuid.UUID(tenant),
                name=key,
                description=description,
                scope="global",
                data_type=dtype,
                default_value=value,
                is_secret=is_secret,
            )
            db.add(av)

    # Handle RAG Documents (FAQs) — index FAQ content for retrieval
    # Collect pending indexing jobs; they are enqueued AFTER commit to ensure
    # the document row exists in DB before the worker tries to process it.
    _pending_indexing_jobs: list[dict] = []
    for key, value in variable_values.items():
        if key.lower() == "faqs" and value:
            import hashlib
            from pathlib import Path
            from app.api.v1.documents import _process_document

            content_str = str(value)
            content_bytes = content_str.encode("utf-8")
            content_hash = hashlib.sha256(content_bytes).hexdigest()

            # Deduplication Check: Skip if this exact content already exists for this agent
            dup_res = await db.execute(
                select(AgentDocument).where(
                    AgentDocument.agent_id == agent.id,
                    AgentDocument.tenant_id == uuid.UUID(tenant),
                    AgentDocument.content_hash == content_hash,
                ).limit(1)
            )
            existing_doc = dup_res.scalar_one_or_none()
            if existing_doc:
                logger.info("template_faq_deduplication_hit", agent_id=str(agent.id), doc_id=str(existing_doc.id))
                continue

            doc_uuid = uuid.uuid4()
            storage_dir = Path(settings.DOCUMENT_STORAGE_PATH) / tenant / str(agent.id)
            storage_dir.mkdir(parents=True, exist_ok=True)
            safe_filename = f"{doc_uuid}_faq.txt"
            storage_path = str(storage_dir / safe_filename)

            try:
                with open(storage_path, "w", encoding="utf-8") as f:
                    # Sanitize FAQs: removal of extremely long lines or common PII patterns could go here
                    f.write(content_str)

                doc = AgentDocument(
                    id=doc_uuid,
                    agent_id=agent.id,
                    tenant_id=uuid.UUID(tenant),
                    name="Frequently Asked Questions",
                    file_type="txt",
                    file_size_bytes=len(content_bytes),
                    storage_path=storage_path,
                    content_hash=content_hash,
                    status="processing",
                )
                db.add(doc)
                _pending_indexing_jobs.append({
                    "document_id": str(doc.id),
                    "agent_id": str(agent.id),
                    "tenant_id": tenant,
                    "content": content_str,
                    "filename": "Frequently Asked Questions",
                    "file_type": "txt"
                })
            except Exception as exc:
                logger.error("template_faq_rag_failed", agent_id=str(agent.id), error=str(exc))

    # Commit all changes atomically before scheduling background tasks.
    # If the commit fails, no background tasks fire — preventing workers from
    # referencing DB rows that were rolled back.
    await db.commit()
    await db.refresh(agent)

    # 4. Enqueue indexing jobs in the durable worker queue
    if _pending_indexing_jobs:
        indexer = request.app.state.document_indexer
        for job in _pending_indexing_jobs:
            await indexer.enqueue(job)
            logger.info("template_faq_queued", doc_id=job["document_id"], agent_id=str(agent.id))

    logger.info(
        "template_instantiated_successfully",
        template_id=str(t_uuid),
        agent_id=str(agent.id),
        tenant_id=tenant,
        playbooks_created=len(playbooks_data),
    )
    return agent.to_dict()

