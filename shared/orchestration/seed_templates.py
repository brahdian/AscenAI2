"""
Zenith State Production-Grade Template Seeder
Architected for the Canadian SMB market with total compliance and operational depth.
This is the definitive, modular implementation of all 22 enterprise templates.
"""
from __future__ import annotations

import uuid
import structlog
from typing import Any, Dict, List
from sqlalchemy import select, delete
from sqlalchemy.dialects.postgresql import insert

from app.core.database import AsyncSessionLocal
from app.models.template import AgentTemplate, TemplateVersion, TemplateVariable, TemplatePlaybook, TemplateTool

# Import playbooks from modular files to avoid monolithic files and token limits
from .seed_template_common import get_common_playbooks
from .seed_template_playbooks_1 import get_playbooks_part_1
from .seed_template_playbooks_2 import get_playbooks_part_2
from .seed_template_playbooks_3 import get_playbooks_part_3
from .seed_template_playbooks_4 import get_playbooks_part_4

logger = structlog.get_logger(__name__)

async def seed_templates() -> None:
    """
    Idempotent seeding engine for Zenith State templates.
    Ensures 22 templates, 242 total playbooks are accurately persisted to the DB.
    """
    async with AsyncSessionLocal() as db:
        try:
            # Aggregate all 22 templates
            ALL_TEMPLATES: Dict[str, List[Dict[str, Any]]] = {}
            ALL_TEMPLATES.update(get_playbooks_part_1())
            ALL_TEMPLATES.update(get_playbooks_part_2())
            ALL_TEMPLATES.update(get_playbooks_part_3())
            ALL_TEMPLATES.update(get_playbooks_part_4())

            common_playbooks = get_common_playbooks()

            for key, specific_pbs in ALL_TEMPLATES.items():
                name = key.replace("_", " ").title()
                
                # Determine Category based on key (basic heuristic)
                category = "general"
                if "support" in key or "help" in key or "success" in key:
                    category = "support"
                elif "sales" in key or "lead" in key or "quote" in key:
                    category = "sales"
                elif "health" in key or "medical" in key:
                    category = "healthcare"
                elif "receptionist" in key or "booking" in key or "routing" in key:
                    category = "routing"
                elif "legal" in key:
                    category = "legal"
                elif "financ" in key:
                    category = "finance"

                # 1. AgentTemplate (Atomic Upsert)
                stmt = insert(AgentTemplate).values(
                    id=uuid.uuid4(), 
                    key=key, 
                    name=name,
                    description=f"Zenith State {name} Template for Canadian SMBs.", 
                    category=category,
                    is_active=True
                ).on_conflict_do_update(
                    index_elements=["key"], 
                    set_={"name": name, "description": f"Zenith State {name} Template for Canadian SMBs."}
                ).returning(AgentTemplate.id)
                tpl_id = (await db.execute(stmt)).scalar_one()

                # 2. TemplateVersion (v1 Persistence)
                ver_stmt = select(TemplateVersion).where(
                    TemplateVersion.template_id == tpl_id, 
                    TemplateVersion.version == 1
                )
                existing_ver = (await db.execute(ver_stmt)).scalar_one_or_none()
                
                v_data = {
                    "system_prompt_template": f"You are a production-grade AI for $vars:business_name. Role: {name}.",
                    "voice_greeting": f"Welcome to $vars:business_name. I am the virtual {name.lower()}. May I have your name and how I can help you today?",
                    "compliance": {"framework": "PIPEDA", "jurisdiction": "Canada"}, 
                    "guardrails": {"pii_masking": True, "safety_interlock": True}, 
                    "emergency_protocols": {"911_routing": True, "crisis_handover": True}
                }
                if existing_ver:
                    ver_id = existing_ver.id
                    existing_ver.system_prompt_template = v_data["system_prompt_template"]
                    existing_ver.voice_greeting = v_data["voice_greeting"]
                    existing_ver.compliance = v_data["compliance"]
                    existing_ver.guardrails = v_data["guardrails"]
                    existing_ver.emergency_protocols = v_data["emergency_protocols"]
                else:
                    ver_id = uuid.uuid4()
                    db.add(TemplateVersion(id=ver_id, template_id=tpl_id, version=1, **v_data))

                # 3. Clean existing nested resources for idempotency
                await db.execute(delete(TemplatePlaybook).where(TemplatePlaybook.template_version_id == ver_id))
                await db.execute(delete(TemplateVariable).where(TemplateVariable.template_id == tpl_id))
                
                # 4. Core Variables
                core_vars = [
                    {"key": "business_name", "label": "Business Name", "type": "text", "is_required": True},
                    {"key": "hours", "label": "Business Hours", "type": "text", "is_required": False, "default_value": {"value": "9am-5pm"}},
                    {"key": "location", "label": "Location/Address", "type": "text", "is_required": False},
                    {"key": "province", "label": "Province (Tax Context)", "type": "text", "is_required": False, "default_value": {"value": "Ontario"}},
                    {"key": "services", "label": "List of Services Offered", "type": "text", "is_required": False, "default_value": {"value": "General Inquiry, Booking, Support"}},
                    {"key": "pricing", "label": "Pricing Information", "type": "text", "is_required": False},
                    {"key": "team_members", "label": "Team Members/Staff", "type": "text", "is_required": False},
                ]
                for v in core_vars:
                    db.add(TemplateVariable(
                        id=uuid.uuid4(), 
                        template_id=tpl_id, 
                        key=v["key"], 
                        label=v["label"],
                        type=v["type"], 
                        is_required=v["is_required"], 
                        default_value=v.get("default_value")
                    ))

                # 5. Playbooks (Merge 6 specific + 5 common = 11 total per template)
                all_playbooks_for_template = specific_pbs + common_playbooks
                
                for pb in all_playbooks_for_template:
                    db.add(TemplatePlaybook(
                        id=uuid.uuid4(), 
                        template_version_id=ver_id,
                        name=pb["name"], 
                        description=pb["description"],
                        trigger_condition=pb["trigger_condition"],
                        is_default=pb.get("is_default", False),
                        config={
                            "instructions": pb["instructions"], 
                            "tone": pb["tone"],
                            "dos": pb["dos"], 
                            "donts": pb["donts"], 
                            "scenarios": pb["scenarios"],
                            "fallback_response": pb["fallback_response"], 
                            "out_of_scope_response": pb["out_of_scope_response"]
                        }
                    ))

            await db.commit()
            total_pbs = sum(len(pbs) for pbs in ALL_TEMPLATES.values()) + (len(ALL_TEMPLATES) * len(common_playbooks))
            logger.info("zenith_seeding_complete", total_templates=len(ALL_TEMPLATES), expected_playbooks=total_pbs)

        except Exception as exc:
            await db.rollback()
            logger.error("zenith_seed_failed", error=str(exc))
            raise exc
