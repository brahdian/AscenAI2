import uuid
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
from app.core.security import get_tenant_db, get_current_tenant
from app.models.agent import Agent, AgentPlaybook, AgentGuardrails, AgentDocument
from app.models.variable import AgentVariable
from app.models.template import (
    AgentTemplate,
    TemplateVersion,
    AgentTemplateInstance,
)
from app.schemas.template import AgentTemplateSchema, TemplateInstantiationRequest, AgentTemplateInstanceSchema

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["Templates"])

# IMPORTANT: Routes with literal path segments (e.g. /instances/...) MUST be
# registered BEFORE parameterized routes (e.g. /{template_id}) so FastAPI
# does not greedily match the literal segment as a parameter value.

# ---------------------------------------------------------------------------
# Instance endpoints — registered first to prevent shadowing by /{template_id}
# ---------------------------------------------------------------------------

@router.get("/instances/by-agent/{agent_id}", response_model=Optional[AgentTemplateInstanceSchema])
async def get_instance_by_agent(
    agent_id: str,
    tenant=Depends(get_current_tenant),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Retrieve the template instance applied to an agent, if any."""
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
    tenant=Depends(get_current_tenant),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Update variable values of a template instance and re-apply to the agent."""
    try:
        i_uuid = uuid.UUID(instance_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID for instance_id")

    # Fetch instance along with related template version
    result = await db.execute(
        select(AgentTemplateInstance)
        .where(
            AgentTemplateInstance.id == i_uuid,
            AgentTemplateInstance.tenant_id == tenant
        )
        .options(selectinload(AgentTemplateInstance.template_version))
    )
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
    
    version = instance.template_version
    if agent and version and version.system_prompt_template:
        rendered_prompt = version.system_prompt_template
        for k, v in instance.variable_values.items():
            rendered_prompt = rendered_prompt.replace(f"{{{{{k}}}}}", str(v))
        agent.system_prompt = rendered_prompt
        
    await db.commit()
    await db.refresh(instance)
    return instance


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
    tenant: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_tenant_db),
):
    """
    Instantiate a template onto an existing agent.
    Applies the template version's rules, copying playbooks and setting prompts based on variable values.
    Template catalog is read without RLS; instance is written into the tenant's RLS context.
    """
    try:
        t_uuid = uuid.UUID(template_id)
        v_uuid = uuid.UUID(body.template_version_id)
        a_uuid = uuid.UUID(body.agent_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format in request")

    # Verify agent exists for tenant (uses get_tenant_db — RLS guards this)
    agent_res = await db.execute(
        select(Agent).where(Agent.id == a_uuid, Agent.tenant_id == uuid.UUID(tenant))
    )
    agent = agent_res.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # -----------------------------------------------------------------------
    # Retrieve template version from the global catalog using a NO-RLS session.
    # IMPORTANT: Extract ALL data we need into plain Python objects INSIDE the
    # `async with` block, before the session closes. Accessing ORM relationship
    # attributes on detached objects (after session close) raises
    # DetachedInstanceError, which would silently skip playbook creation.
    # -----------------------------------------------------------------------
    system_prompt_template: str | None = None
    playbooks_data: list[dict] = []
    tools_data: list[dict] = []

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
        version_id = version.id

        for pbook in version.playbooks:
            playbook_config = dict(pbook.config) if pbook.config else {}
            playbooks_data.append({
                "name": pbook.name,
                "description": pbook.description,
                "trigger_condition": dict(pbook.trigger_condition) if pbook.trigger_condition else {},
                "flow_definition": playbook_config.get("flow_definition", {}),
                "tone": playbook_config.get("tone", "professional"),
                "dos": playbook_config.get("dos", []),
                "donts": playbook_config.get("donts", []),
                "scenarios": playbook_config.get("scenarios", []),
                "out_of_scope_response": playbook_config.get("out_of_scope_response"),
                "fallback_response": playbook_config.get("fallback_response"),
                "custom_escalation_message": playbook_config.get("custom_escalation_message"),
                "is_default": pbook.is_default
            })

        for vt in version.tools:
            tools_data.append({
                "tool_name": vt.tool_name,
                "required_config_schema": dict(vt.required_config_schema) if vt.required_config_schema else {},
            })
    # catalog_db is now safely closed — we work only with plain dicts from here.

    logger.info(
        "template_instantiate_catalog_loaded",
        template_id=template_id,
        version_id=str(version_id),
        playbook_count=len(playbooks_data),
        tool_count=len(tools_data),
    )

    # -----------------------------------------------------------------------
    # Helper: substitute {{key}} and {key} template variables in a string
    # -----------------------------------------------------------------------
    def _render(text: str) -> str:
        for k, v in body.variable_values.items():
            text = text.replace("{{" + k + "}}", str(v))
            text = text.replace("{" + k + "}", str(v))
        return text

    # Update agent system prompt by substituting variable_values
    if system_prompt_template:
        agent.system_prompt = _render(system_prompt_template)

    # Add tool configurations
    if tools_data:
        agent_cfg = agent.agent_config or {}
        agent_tools = list(agent_cfg.get("tools", []) or [])
        for vt in tools_data:
            tool_cfg = body.tool_configs.get(vt["tool_name"], {})
            agent_tools.append({
                "name": vt["tool_name"],
                "config": tool_cfg,
            })
        agent.agent_config["tools"] = agent_tools

    # -----------------------------------------------------------------------
    # Delete the auto-generated default playbooks so template ones replace them
    # -----------------------------------------------------------------------
    await db.execute(
        delete(AgentPlaybook).where(
            AgentPlaybook.agent_id == agent.id,
        )
    )

    # Copy template playbooks as AgentPlaybook rows
    first_playbook = True
    for pbook in playbooks_data:
        flow = pbook.get("flow_definition", {})
        trigger_condition = pbook.get("trigger_condition", {})
        triggers = trigger_condition.get("keywords", []) if isinstance(trigger_condition, dict) else []

        instructions_parts: list[str] = []
        if "steps" in flow:
            for step in flow["steps"]:
                if "instruction" in step:
                    instructions_parts.append(step["instruction"])
        instructions = _render("\n\n".join(instructions_parts))
        if not instructions:
            instructions = _render(pbook.get("description") or "")

        description = _render(pbook.get("description") or "")
        tone = _render(pbook.get("tone") or "professional")
        dos = [_render(str(item)) for item in (pbook.get("dos") or [])]
        donts = [_render(str(item)) for item in (pbook.get("donts") or [])]
        scenarios_raw = pbook.get("scenarios") or []
        out_of_scope_response = _render(pbook.get("out_of_scope_response") or "")
        fallback_response = _render(pbook.get("fallback_response") or "")
        custom_escalation_message = _render(pbook.get("custom_escalation_message") or "")
        is_default = pbook.get("is_default", False)

        rendered_scenarios = [
            {
                "trigger": _render(s.get("trigger", "")),
                "response": _render(s.get("response", "")),
            }
            for s in scenarios_raw
        ]

        # Render all {{variables}} inside flow_definition (step instructions, labels, etc.)
        import json as _json
        rendered_flow = _json.loads(_render(_json.dumps(flow))) if flow else flow

        mark_default = is_default or first_playbook
        first_playbook = False

        playbook = AgentPlaybook(
            agent_id=agent.id,
            tenant_id=uuid.UUID(tenant),
            name=pbook["name"],
            description=description or None,
            intent_triggers=triggers,
            config={
                "instructions": instructions,
                "tone": tone,
                "dos": dos,
                "donts": donts,
                "scenarios": rendered_scenarios,
                "out_of_scope_response": out_of_scope_response or None,
                "fallback_response": fallback_response or None,
                "custom_escalation_message": custom_escalation_message or None,
                "flow_definition": rendered_flow,
            },
            is_active=True,
            is_default=mark_default,
        )
        db.add(playbook)
        logger.info("template_playbook_added", name=pbook["name"], agent_id=str(agent.id))

    # Update existing Guardrails, or create if missing
    gr_res = await db.execute(select(AgentGuardrails).where(AgentGuardrails.agent_id == agent.id))
    guardrails = gr_res.scalar_one_or_none()
    
    if guardrails:
        guardrails.config["pii_redaction"] = True
        guardrails.config["profanity_filter"] = True
        guardrails.is_active = True
        flag_modified(guardrails, "config")
    else:
        guardrails = AgentGuardrails(
            agent_id=agent.id,
            tenant_id=uuid.UUID(tenant),
            config={
                "pii_redaction": True,
                "profanity_filter": True,
                "pii_pseudonymization": True,
                "is_active": True,
            },
            is_active=True,
        )
        db.add(guardrails)

    # Record the template instance (this proves instantiation succeeded)
    instance = AgentTemplateInstance(
        tenant_id=uuid.UUID(tenant),
        agent_id=agent.id,
        template_version_id=version_id,
        variable_values=body.variable_values,
        tool_configs=body.tool_configs,
    )
    db.add(instance)

    # ------------------------------------------------------------------
    # Sync template variable_values → agent_variables table so they are
    # visible and editable on the Variables page in the UI.
    # Skip internal routing keys that have no meaning as runtime variables.
    # ------------------------------------------------------------------
    _SKIP_VARIABLE_KEYS = {"business_type", "language"}

    # Fetch the template's variable definitions so we can copy labels/types
    var_defs: dict[str, dict] = {}
    for ver_data in playbooks_data:  # reuse already-loaded catalog data
        break  # just need the version; template vars are in version.variables
    # Re-query from the already-detached template_vars_data (stored earlier)
    for tvar in getattr(version, "variables", []) if hasattr(version, "variables") else []:
        var_defs[tvar.key] = {
            "label": tvar.label,
            "type": tvar.type,
            "required": tvar.is_required,
        }

    # Delete any existing template-sourced variables before re-seeding so
    # re-instantiation (e.g., after variable edit) doesn't create duplicates.
    existing_vars_res = await db.execute(
        select(AgentVariable).where(AgentVariable.agent_id == agent.id)
    )
    existing_var_names = {v.name: v for v in existing_vars_res.scalars().all()}

    for key, value in body.variable_values.items():
        if key in _SKIP_VARIABLE_KEYS or key.lower() == "faqs":
            continue  # FAQs become documents; routing keys are noise

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
        tvar_meta = var_defs.get(key, {})
        description = tvar_meta.get("label") or key.replace("_", " ").title()

        if key in existing_var_names:
            # Update existing — preserve scope/secret settings
            ev = existing_var_names[key]
            ev.default_value = value
            ev.description = description
            ev.data_type = dtype
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
                is_secret=False,
            )
            db.add(av)

    # Handle RAG Documents (FAQs) — index FAQ content for retrieval
    # Collect pending background tasks; they are scheduled AFTER commit to ensure
    # the document row exists in DB before the background worker tries to read it.
    _pending_background_tasks: list[tuple] = []
    for key, value in body.variable_values.items():
        if key.lower() == "faqs" and value:
            from pathlib import Path
            from app.api.v1.documents import _process_document

            doc_uuid = uuid.uuid4()
            storage_dir = Path(settings.DOCUMENT_STORAGE_PATH) / tenant / str(agent.id)
            storage_dir.mkdir(parents=True, exist_ok=True)
            safe_filename = f"{doc_uuid}_faq.txt"
            storage_path = str(storage_dir / safe_filename)

            try:
                with open(storage_path, "w", encoding="utf-8") as f:
                    f.write(str(value))

                doc = AgentDocument(
                    id=doc_uuid,
                    agent_id=agent.id,
                    tenant_id=uuid.UUID(tenant),
                    name="Frequently Asked Questions",
                    file_type="txt",
                    file_size_bytes=len(str(value).encode("utf-8")),
                    storage_path=storage_path,
                    status="processing",
                )
                db.add(doc)
                # Queue task for post-commit scheduling — not yet registered
                _pending_background_tasks.append((
                    _process_document,
                    dict(doc_id=str(doc.id), file_path=storage_path,
                         agent_id=str(agent.id), tenant_id=tenant),
                ))
            except Exception as exc:
                logger.error("template_faq_rag_failed", agent_id=str(agent.id), error=str(exc))

    # Commit all changes atomically before scheduling background tasks.
    # If the commit fails, no background tasks fire — preventing workers from
    # referencing DB rows that were rolled back.
    await db.commit()
    await db.refresh(agent)

    for fn, kwargs in _pending_background_tasks:
        background_tasks.add_task(fn, **kwargs)

    logger.info(
        "template_instantiated_successfully",
        template_id=template_id,
        agent_id=str(agent.id),
        tenant_id=tenant,
        playbooks_created=len(playbooks_data),
    )
    return agent.to_dict()

