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
from shared.orchestration.mcp_client import MCPClient
from shared.orchestration.settings_service import SettingsService
import shared.pii as pii_service

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
        return await SettingsService.get_setting(self.db, "platform_guardrails", default={})

    async def load_platform_limits(self) -> dict:
        """Fetch platform-wide response conciseness limits (admin-configurable)."""
        return await SettingsService.get_setting(self.db, "global_response_limits", default={})

    async def load_corrections(self, agent_id: str) -> List[dict]:
        if self.redis is None:
            return []
        
        key = f"corrections:{agent_id}"
        try:
            raw_items = await self.redis.lrange(key, 0, 19)
            if raw_items:
                corrections = []
                for raw in raw_items:
                    try:
                        corrections.append(json.loads(raw))
                    except Exception as e:
                        logger.warning("correction_parse_failed", raw=raw[:100], error=str(e))
                return corrections
            
            # --- SELF-HEALING FALLBACK ---
            # If cache is empty, pull the 20 most recent corrections from DB
            from app.models.agent import MessageFeedback, Message
            from sqlalchemy.orm import aliased
            
            UserMsg = aliased(Message)
            result = await self.db.execute(
                select(MessageFeedback, Message.content, UserMsg.content)
                .join(Message, Message.id == MessageFeedback.message_id)
                .outerjoin(UserMsg, and_(
                    UserMsg.session_id == Message.session_id,
                    UserMsg.role == "user",
                    UserMsg.created_at < Message.created_at
                ))
                .where(MessageFeedback.agent_id == uuid.UUID(agent_id))
                .where(MessageFeedback.ideal_response.is_not(None))
                .order_by(MessageFeedback.created_at.desc())
                .limit(20)
            )
            
            rows = result.all()
            if not rows:
                return []
            
            db_corrections = []
            redis_entries = []
            for fb, asst_content, user_content in rows:
                entry = {
                    "user_message": (user_content or "")[:300],
                    "ideal_response": pii_service.redact((fb.ideal_response or ""))[:800],
                    "playbook_correction": pii_service.redact((fb.playbook_correction or "")),
                    "tool_corrections": fb.tool_corrections or [],
                    "ts": fb.created_at.timestamp() if fb.created_at else 0,
                }
                db_corrections.append(entry)
                redis_entries.append(json.dumps(entry))
            
            # Re-prime Redis cache (LIFO push)
            if redis_entries:
                try:
                    pipe = self.redis.pipeline()
                    # Push in reverse order so latest is at the front (lpush)
                    for re in reversed(redis_entries):
                        pipe.lpush(key, re)
                    pipe.ltrim(key, 0, 19)
                    pipe.expire(key, 60 * 60 * 24 * 30) # 30 days
                    await pipe.execute()
                    logger.info("corrections_cache_reprimed", agent_id=agent_id, count=len(redis_entries))
                except Exception as e:
                    logger.warning("corrections_cache_reprime_failed", agent_id=agent_id, error=str(e))
            
            return db_corrections
            
        except Exception as e:
            logger.warning("corrections_load_failed", agent_id=agent_id, error=str(e))
            return []

    async def load_variables(self, agent_id: str, playbook_id: Optional[str] = None) -> List[AgentVariable]:
        # FIX-12: Cache the variable list to avoid a per-turn DB query at scale
        cache_key = f"agent_variables:{agent_id}:{playbook_id or 'global'}"
        if self.redis:
            try:
                cached = await self.redis.get(cache_key)
                if cached:
                    import json as _json
                    # We can't cache ORM objects — we need raw dicts; skip cache for now
                    # and use the cache only as a "has variables" hint below.
                    # Full ORM cache requires a separate schema; fall through to DB.
                    pass
            except Exception as e:
                logger.warning("redis_variables_cache_load_failed", agent_id=agent_id, error=str(e))

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
        variables = list(result.scalars().all())

        # Cache the list of variable names (cheap sentinel) to detect mis-configured agents
        if self.redis and variables:
            try:
                import json as _json
                names = [v.name for v in variables]
                await self.redis.setex(cache_key + ":names", 60, _json.dumps(names))
            except Exception as e:
                logger.warning("redis_variables_cache_set_failed", agent_id=agent_id, error=str(e))

        return variables

    async def invalidate_variables_cache(self, agent_id: str) -> None:
        """Call this from variable mutation endpoints to keep the cache coherent."""
        if not self.redis:
            return
        try:
            # Invalidate both global and any per-playbook cache entries
            async for key in self.redis.scan_iter(f"agent_variables:{agent_id}:*"):
                await self.redis.delete(key)
        except Exception as e:
            logger.warning("redis_variables_cache_invalidate_failed", agent_id=agent_id, error=str(e))

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
        voice_system_prompt_template: str = "",
        platform_limits: dict = None,
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
            platform_limits=platform_limits,
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
