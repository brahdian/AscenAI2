import json
import uuid
import structlog
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.agent import AgentPlaybook

logger = structlog.get_logger(__name__)

PLAYBOOK_SUMMARIES_KEY = "playbook_summaries:{agent_id}"
PLAYBOOK_CACHE_TTL = 300


class PlaybookRoutingService:
    def __init__(self, redis_client=None):
        self.redis = redis_client

    def _get_cache_key(self, agent_id: str) -> str:
        return PLAYBOOK_SUMMARIES_KEY.format(agent_id=agent_id)

    async def cache_playbook_summaries(self, agent_id: str, playbooks: List[AgentPlaybook]) -> None:
        if not self.redis:
            logger.warning("redis_not_available_skip_cache")
            return

        try:
            cache_key = self._get_cache_key(agent_id)
            summaries = []
            for p in playbooks:
                playbook_config = p.config or {}
                summary = {
                    "id": str(p.id),
                    "name": p.name,
                    "summary_embedding": self._generate_summary_embedding(p),
                    "trigger_phrases": p.intent_triggers or [],
                    "keywords": playbook_config.get("trigger_condition", {}).get("keywords", []) if isinstance(playbook_config.get("trigger_condition"), dict) else [],
                    "tone": playbook_config.get("tone", "professional"),
                }
                summaries.append(summary)

            await self.redis.setex(cache_key, PLAYBOOK_CACHE_TTL, json.dumps(summaries))
            logger.info("playbook_summaries_cached", agent_id=agent_id, count=len(summaries))
        except Exception as e:
            logger.error("playbook_summary_cache_failed", agent_id=agent_id, error=str(e))

    def _generate_summary_embedding(self, playbook: AgentPlaybook) -> str:
        config = playbook.config or {}
        parts = [
            playbook.name or "",
            playbook.description or "",
            config.get("tone", ""),
            config.get("instructions", "")[:500] if config.get("instructions") else "",
        ]
        return " | ".join(parts).lower()

    async def find_best_playbook(
        self, agent_id: str, user_message: str
    ) -> Optional[str]:
        if not self.redis:
            return None

        try:
            cache_key = self._get_cache_key(agent_id)
            cached = await self.redis.get(cache_key)
            if not cached:
                return None

            summaries = json.loads(cached)
            user_lower = user_message.lower()

            best_score = 0
            best_playbook_id = None

            for summary in summaries:
                score = 0

                keywords = summary.get("trigger_phrases", []) + summary.get("keywords", [])
                for kw in keywords:
                    if isinstance(kw, str) and kw.lower() in user_lower:
                        score += 2
                    if isinstance(kw, str) and kw.lower() in user_lower.split():
                        score += 1

                name_words = summary.get("name", "").lower().split()
                for word in name_words:
                    if len(word) > 3 and word in user_lower:
                        score += 1

                if score > best_score:
                    best_score = score
                    best_playbook_id = summary.get("id")

            if best_score > 0:
                logger.info("playbook_routed", agent_id=agent_id, playbook_id=best_playbook_id, score=best_score)
                return best_playbook_id

        except Exception as e:
            logger.error("playbook_routing_failed", agent_id=agent_id, error=str(e))

        return None

    async def invalidate_cache(self, agent_id: str) -> None:
        if not self.redis:
            return
        try:
            cache_key = self._get_cache_key(agent_id)
            await self.redis.delete(cache_key)
            logger.info("playbook_cache_invalidated", agent_id=agent_id)
        except Exception as e:
            logger.error("playbook_cache_invalidation_failed", agent_id=agent_id, error=str(e))

    async def get_full_playbook(
        self, db: AsyncSession, playbook_id: str
    ) -> Optional[AgentPlaybook]:
        try:
            result = await db.execute(
                select(AgentPlaybook).where(AgentPlaybook.id == uuid.UUID(playbook_id))
            )
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error("playbook_fetch_failed", playbook_id=playbook_id, error=str(e))
            return None

    async def hot_load_playbook(
        self, db: AsyncSession, agent_id: str, playbook_id: str
    ) -> Optional[dict]:
        playbook = await self.get_full_playbook(db, playbook_id)
        if not playbook:
            return None

        config = playbook.config or {}
        return {
            "id": str(playbook.id),
            "name": playbook.name,
            "config": config,
            "intent_triggers": playbook.intent_triggers or [],
        }
