from typing import Optional, List
import json
import uuid
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, and_

from app.models.agent import Agent, AgentPlaybook, AgentGuardrails
from app.models.agent_custom_guardrail import AgentCustomGuardrail
from app.models.variable import AgentVariable
from app.prompts.system_prompts import build_system_prompt
from app.services.mcp_client import MCPClient
from app.services.settings_service import SettingsService

logger = structlog.get_logger(__name__)


class ContextBuilderService:
    def __init__(self, db: AsyncSession, mcp: MCPClient, redis_client=None):
        self.db = db
        self.mcp = mcp
        self.redis = redis_client

    async def load_guardrails(self, agent_id: str) -> Optional[dict]:
        cache_key = f"agent_guardrails:{agent_id}"
        if self.redis:
            try:
                cached = await self.redis.get(cache_key)
                if cached:
                    return json.loads(cached)
            except Exception as e:
                logger.warning("redis_guardrails_load_failed", agent_id=agent_id, error=str(e))

        result = await self.db.execute(
            select(AgentGuardrails).where(AgentGuardrails.agent_id == uuid.UUID(agent_id))
        )
        gr = result.scalar_one_or_none()
        if not gr:
            return None

        config = gr.config or {}
        data = {
            "is_active": gr.is_active,
            "blocked_keywords": config.get("blocked_keywords", []),
            "blocked_topics": config.get("blocked_topics", []),
            "allowed_topics": config.get("allowed_topics", []),
            "pii_redaction": config.get("pii_redaction", False),
            "blocked_message": config.get("blocked_message"),
        }
        if self.redis:
            try:
                await self.redis.setex(cache_key, 300, json.dumps(data))
            except Exception as e:
                logger.warning("redis_guardrails_cache_failed", agent_id=agent_id, error=str(e))
        return data

    async def load_custom_guardrails(self, agent_id: str) -> List[dict]:
        cache_key = f"custom_guardrails:{agent_id}"
        if self.redis:
            try:
                cached = await self.redis.get(cache_key)
                if cached:
                    return json.loads(cached)
            except Exception as e:
                logger.warning("redis_custom_guardrails_load_failed", agent_id=agent_id, error=str(e))

        result = await self.db.execute(
            select(AgentCustomGuardrail).where(
                AgentCustomGuardrail.agent_id == uuid.UUID(agent_id),
                AgentCustomGuardrail.is_active.is_(True)
            )
        )
        items = result.scalars().all()
        data = [{
            "id": str(i.id),
            "rule": i.rule,
            "category": i.category,
            "is_active": i.is_active
        } for i in items]

        if self.redis:
            try:
                await self.redis.setex(cache_key, 300, json.dumps(data))
            except Exception as e:
                logger.warning("redis_custom_guardrails_cache_failed", agent_id=agent_id, error=str(e))
        return data

    async def load_platform_guardrails(self) -> Optional[dict]:
        return await SettingsService.get_setting(self.db, "global_guardrails", default={})

    async def load_corrections(self, agent_id: str) -> List[dict]:
        if self.redis is None:
            return []
        try:
            key = f"corrections:{agent_id}"
            raw_items = await self.redis.lrange(key, 0, 19)
            corrections = []
            for raw in raw_items:
                try:
                    corrections.append(json.loads(raw))
                except Exception as e:
                    logger.warning("correction_parse_failed", raw=raw[:100], error=str(e))
            return corrections
        except Exception as e:
            logger.warning("corrections_load_failed", agent_id=agent_id, error=str(e))
            return []

    async def load_variables(self, agent_id: str, playbook_id: Optional[str] = None) -> List[AgentVariable]:
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
        corrections: List[dict],
        guardrails: Optional[dict],
        custom_guardrails: List[dict],
        platform_guardrails: Optional[dict],
        variables: List[AgentVariable],
        session_meta: dict,
        local_vars: dict,
        voice_system_prompt_template: str = ""
    ) -> str:
        all_variables = {**session_meta.get("variables", {}), **local_vars}

        collated_guardrails = {
            **(guardrails or {}),
            "custom_rules": custom_guardrails or [],
            "global_rules": platform_guardrails or {}
        }

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
            guardrails=collated_guardrails,
            variables=variables,
            session_metadata={**session_meta, "variables": all_variables},
            voice_system_prompt_template=voice_system_prompt_template,
        )

    async def get_agent_tools_schema(
        self, agent: Agent, playbook: Optional[AgentPlaybook], tenant_id: str
    ) -> List[dict]:
        agent_config = agent.agent_config or {}
        system_tools = agent_config.get("tools", []) or []
        
        playbook_tools = []
        if playbook and playbook.config:
            playbook_tools = playbook.config.get("tools", []) or []

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
