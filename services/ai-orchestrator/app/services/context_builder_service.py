from typing import Optional
import json
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, and_

from app.models.agent import Agent, AgentPlaybook, AgentGuardrails
from app.models.variable import AgentVariable
from app.prompts.system_prompts import build_system_prompt
from app.services.mcp_client import MCPClient

class ContextBuilderService:
    def __init__(self, db: AsyncSession, mcp: MCPClient, redis_client=None):
        self.db = db
        self.mcp = mcp
        self.redis = redis_client

    async def load_guardrails(self, agent_id: str) -> Optional[AgentGuardrails]:
        result = await self.db.execute(
            select(AgentGuardrails).where(
                AgentGuardrails.agent_id == agent_id,
                AgentGuardrails.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def load_corrections(self, agent_id: str) -> list[dict]:
        if self.redis is None:
            return []
        try:
            key = f"corrections:{agent_id}"
            raw_items = await self.redis.lrange(key, 0, 19)
            corrections = []
            for raw in raw_items:
                try:
                    corrections.append(json.loads(raw))
                except Exception:
                    pass
            return corrections
        except Exception:
            return []

    async def load_variables(self, agent_id: str, playbook_id: Optional[str] = None) -> list[AgentVariable]:
        filters = [AgentVariable.agent_id == uuid.UUID(agent_id)]
        
        if playbook_id:
            filters.append(
                or_(
                    AgentVariable.scope == "global",
                    and_(
                        AgentVariable.scope == "local",
                        AgentVariable.playbook_id == uuid.UUID(playbook_id)
                    )
                )
            )
        else:
            filters.append(AgentVariable.scope == "global")

        result = await self.db.execute(
            select(AgentVariable).where(*filters)
        )
        return list(result.scalars().all())

    def build_system_prompt(
        self, 
        agent: Agent, 
        context_items: list,
        customer_profile: dict,
        intent: str,
        session_language: Optional[str],
        playbook: Optional[AgentPlaybook],
        corrections: list[dict],
        guardrails: Optional[AgentGuardrails],
        variables: list[AgentVariable],
        session_meta: dict,
        local_vars: dict
    ) -> str:
        all_variables = {**session_meta.get("variables", {}), **local_vars}
        
        return build_system_prompt(
            agent=agent,
            context_items=context_items,
            business_info={
                "customer_profile": customer_profile, 
                "intent": intent,
                "session_language": session_language
            },
            playbook=playbook,
            corrections=corrections,
            guardrails=guardrails,
            variables=variables,
            session_metadata={**session_meta, "variables": all_variables},
        )

    async def get_agent_tools_schema(
        self, agent: Agent, playbook: Optional[AgentPlaybook], tenant_id: str
    ) -> list[dict]:
        system_tools = agent.tools or []
        playbook_tools = playbook.tools or [] if playbook else []
        
        enabled_tools = list(dict.fromkeys(system_tools + playbook_tools))
        
        if not enabled_tools:
            return []

        schemas = await self.mcp.get_tool_schemas(
            tenant_id=tenant_id,
            tool_names=enabled_tools,
        )
        
        schemas.append({
            "name": "set_session_variable",
            "description": "Store a global variable for the entire session. Use this for data that should persist across playbooks (e.g. user name, preferences).",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "The name of the variable."},
                    "value": {"type": "string", "description": "The value to store (stringified)."}
                },
                "required": ["name", "value"]
            }
        })
        schemas.append({
            "name": "set_playbook_variable",
            "description": "Store a local variable for the current playbook. Use this for transient data needed for the current task (e.g. temporary IDs, flags).",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "The name of the variable."},
                    "value": {"type": "string", "description": "The value to store (stringified)."}
                },
                "required": ["name", "value"]
            }
        })
        
        return schemas
