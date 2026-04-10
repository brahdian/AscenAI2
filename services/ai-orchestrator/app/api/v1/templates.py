import uuid
from typing import List
import structlog

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, Request
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Dict, Any

# AgentTemplate rows are GLOBAL seed data — they have no tenant_id column and
# must be read with a session that bypasses RLS (get_db_no_rls).
# AgentTemplateInstance rows ARE tenant-scoped and use get_tenant_db.
from app.core.database import get_db, get_db_no_rls, AsyncSessionLocal
from app.core.config import settings
from app.core.security import get_tenant_db, get_current_tenant
from app.models.agent import Agent, AgentPlaybook, AgentGuardrails, AgentDocument
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

@router.get("/instances/by-agent/{agent_id}", response_model=AgentTemplateInstanceSchema)
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
    if not instance:
        raise HTTPException(status_code=404, detail="No template instance found for this agent")
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

    # Update variable values
    current_vars = instance.variable_values or {}
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
    # tenant is provided by Depends(get_current_tenant)
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
        
    # Retrieve template version — read WITHOUT RLS because template tables are global
    # We open a separate no-RLS session just for this read-only catalog lookup.
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

    # Update agent system prompt by substituting variable_values
    if version.system_prompt_template:
        rendered_prompt = version.system_prompt_template
        for k, v in body.variable_values.items():
            rendered_prompt = rendered_prompt.replace("{{" + k + "}}", str(v))
        agent.system_prompt = rendered_prompt

    # Add tool configurations
    if version.tools:
        agent_tools = list(agent.tools or [])
        for vt in version.tools:
            tool_cfg = body.tool_configs.get(vt.tool_name, {})
            agent_tools.append({
                "name": vt.tool_name,
                "config": tool_cfg
            })
        agent.tools = agent_tools

    # Copy template playbooks as AgentPlaybook rows
    first_playbook = True
    for pbook in version.playbooks:
        # Map TemplatePlaybook (trigger_condition, flow_definition) 
        # to AgentPlaybook (intent_triggers, instructions, + rich fields)
        triggers = pbook.trigger_condition.get("keywords", []) if pbook.trigger_condition else []
        flow = pbook.flow_definition or {}
        
        # Aggregate instructions from all steps
        instructions_list = []
        if "steps" in flow:
            for step in flow["steps"]:
                if "instruction" in step:
                    instructions_list.append(step["instruction"])
        
        instructions = "\n\n".join(instructions_list)

        # Helper: substitute template variables in a string
        def _render(text: str) -> str:
            for k, v in body.variable_values.items():
                text = text.replace("{{" + k + "}}", str(v))
                text = text.replace("{" + k + "}", str(v))
            return text

        # Substitute variables in playbook instructions
        rendered_instructions = _render(instructions)

        # Extract rich metadata from flow_definition
        description = flow.get("description")
        tone = flow.get("tone", "professional")
        dos = flow.get("dos", [])
        donts = flow.get("donts", [])
        scenarios = flow.get("scenarios", [])
        out_of_scope_response = flow.get("out_of_scope_response")
        fallback_response = flow.get("fallback_response")
        custom_escalation_message = flow.get("custom_escalation_message")
        is_default = flow.get("is_default", False)

        # Render variable substitutions in string fields
        if out_of_scope_response:
            out_of_scope_response = _render(out_of_scope_response)
        if fallback_response:
            fallback_response = _render(fallback_response)
        if custom_escalation_message:
            custom_escalation_message = _render(custom_escalation_message)
        if description:
            description = _render(description)

        # Render variables in scenarios
        rendered_scenarios = []
        for s in scenarios:
            rendered_scenarios.append({
                "trigger": _render(s.get("trigger", "")),
                "response": _render(s.get("response", "")),
            })

        # Use is_default from template, or mark first playbook as default
        mark_default = is_default or first_playbook
        first_playbook = False

        playbook = AgentPlaybook(
            agent_id=agent.id,
            tenant_id=uuid.UUID(tenant),
            name=pbook.name,
            description=description,
            intent_triggers=triggers,
            instructions=rendered_instructions,
            tone=tone,
            dos=dos,
            donts=donts,
            scenarios=rendered_scenarios,
            out_of_scope_response=out_of_scope_response,
            fallback_response=fallback_response,
            custom_escalation_message=custom_escalation_message,
            is_active=True,
            is_default=mark_default,
        )
        db.add(playbook)

    # Enable "Perfect Guardrails" by default
    guardrails = AgentGuardrails(
        agent_id=agent.id,
        tenant_id=uuid.UUID(tenant),
        pii_redaction=True,
        profanity_filter=True,
        is_active=True
    )
    db.add(guardrails)

    instance = AgentTemplateInstance(
        tenant_id=uuid.UUID(tenant),
        agent_id=agent.id,
        template_version_id=version.id,
        variable_values=body.variable_values,
        tool_configs=body.tool_configs
    )
    db.add(instance)

    # --- 4. Handle RAG Documents (FAQs) ---
    # Collect pending background tasks; they are scheduled AFTER commit to ensure
    # the document row exists in DB before the background worker tries to read it.
    _pending_background_tasks: list[tuple] = []
    for key, value in body.variable_values.items():
        if key.lower() == "faqs" and value:
            from pathlib import Path
            from app.api.v1.documents import _process_document

            doc_uuid = uuid.uuid4()
            doc_name = "Frequently Asked Questions"

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
                    name=doc_name,
                    file_type="txt",
                    file_size_bytes=len(str(value)),
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

    # --- 5. Cleanup redundant playbooks ---
    from sqlalchemy import delete
    await db.execute(
        delete(AgentPlaybook).where(
            AgentPlaybook.agent_id == agent.id,
            AgentPlaybook.name == "Default",
            AgentPlaybook.is_default == True
        )
    )

    # Commit all changes atomically before scheduling background tasks.
    # If the commit fails, no background tasks fire — preventing workers from
    # referencing DB rows that were rolled back.
    await db.commit()
    await db.refresh(agent)

    for fn, kwargs in _pending_background_tasks:
        background_tasks.add_task(fn, **kwargs)

    return agent.to_dict()
