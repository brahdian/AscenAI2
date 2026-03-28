"""
PromptManager — versioned prompt management with A/B routing and Redis cache.

Responsibilities:
  - Create immutable prompt versions
  - Activate / deactivate versions (one active per agent+environment at a time)
  - Route sessions to a prompt version (A/B test or default)
  - Cache active prompt in Redis with 5-minute TTL
  - Invalidate cache on activation / rollback

Cache key:  ``active_prompt:{agent_id}:{environment}``
TTL:        300 seconds (5 minutes)
"""
from __future__ import annotations

import difflib
import hashlib
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.prompt import PromptABTest, PromptVersion

logger = structlog.get_logger(__name__)

_CACHE_TTL = 300  # 5 minutes


def _cache_key(agent_id: str, environment: str = "production") -> str:
    return f"active_prompt:{agent_id}:{environment}"


class PromptManager:
    """
    Manages versioned system prompts for an agent.

    :param db: SQLAlchemy async session
    :param redis_client: async Redis client
    """

    def __init__(self, db: AsyncSession, redis_client) -> None:
        self._db = db
        self._redis = redis_client

    # ── Version creation ──────────────────────────────────────────────────────

    async def create_version(
        self,
        tenant_id: uuid.UUID,
        agent_id: uuid.UUID,
        content: str,
        environment: str = "all",
        change_notes: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> PromptVersion:
        """Create a new (inactive) immutable prompt version."""
        # Determine next version number
        result = await self._db.execute(
            select(func.max(PromptVersion.version_number)).where(
                PromptVersion.agent_id == agent_id,
                PromptVersion.environment == environment,
            )
        )
        max_ver = result.scalar() or 0

        version = PromptVersion(
            tenant_id=tenant_id,
            agent_id=agent_id,
            content=content,
            environment=environment,
            version_number=max_ver + 1,
            change_notes=change_notes,
            created_by=created_by,
            is_active=False,
        )
        self._db.add(version)
        await self._db.flush()
        logger.info(
            "prompt_version_created",
            agent_id=str(agent_id),
            version_id=str(version.id),
            version_number=version.version_number,
        )
        return version

    # ── Activation ────────────────────────────────────────────────────────────

    async def activate_version(
        self,
        version_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> PromptVersion:
        """
        Activate a prompt version.

        Deactivates any currently-active version for the same
        (agent_id, environment) combination first.
        Invalidates the Redis cache.
        """
        result = await self._db.execute(
            select(PromptVersion).where(
                PromptVersion.id == version_id,
                PromptVersion.tenant_id == tenant_id,
            )
        )
        version = result.scalar_one_or_none()
        if not version:
            raise ValueError(f"Prompt version {version_id} not found")

        # Deactivate current active version
        current = await self._db.execute(
            select(PromptVersion).where(
                PromptVersion.agent_id == version.agent_id,
                PromptVersion.environment == version.environment,
                PromptVersion.is_active.is_(True),
                PromptVersion.id != version_id,
            )
        )
        for v in current.scalars().all():
            v.is_active = False
            v.deactivated_at = datetime.now(timezone.utc)

        version.is_active = True
        version.activated_at = datetime.now(timezone.utc)
        version.deactivated_at = None

        await self._db.flush()
        await self._invalidate_cache(str(version.agent_id), version.environment)

        logger.info(
            "prompt_version_activated",
            agent_id=str(version.agent_id),
            version_id=str(version_id),
            version_number=version.version_number,
            environment=version.environment,
        )
        return version

    async def rollback(
        self,
        target_version_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> PromptVersion:
        """Activate a previous version (rollback). Semantically identical to activate."""
        return await self.activate_version(target_version_id, tenant_id)

    # ── Routing ───────────────────────────────────────────────────────────────

    async def get_prompt_for_session(
        self,
        agent_id: uuid.UUID,
        tenant_id: uuid.UUID,
        session_id: str,
        environment: str = "production",
    ) -> Optional[str]:
        """
        Return the system prompt content to use for a given session.

        If an active A/B test exists for this agent, routes the session
        deterministically using ``hash(session_id) % 100``.

        Falls back to the agent's current active prompt version.
        Returns None if no active version exists (caller should use
        the agent.system_prompt field directly).
        """
        # 1. Check for active A/B test
        ab_result = await self._db.execute(
            select(PromptABTest).where(
                PromptABTest.agent_id == agent_id,
                PromptABTest.status == "active",
            ).limit(1)
        )
        ab_test = ab_result.scalar_one_or_none()
        if ab_test:
            bucket = int(hashlib.md5(session_id.encode()).hexdigest(), 16) % 100
            version_id = (
                ab_test.version_a_id
                if bucket < ab_test.traffic_split_percent
                else ab_test.version_b_id
            )
            ver_result = await self._db.execute(
                select(PromptVersion).where(PromptVersion.id == version_id)
            )
            version = ver_result.scalar_one_or_none()
            if version:
                logger.debug(
                    "prompt_ab_routing",
                    session_id=session_id,
                    bucket=bucket,
                    ab_test_id=str(ab_test.id),
                    version_id=str(version_id),
                )
                return version.content

        # 2. Cache lookup
        cached = await self._redis.get(_cache_key(str(agent_id), environment))
        if cached:
            return cached.decode() if isinstance(cached, bytes) else cached

        # 3. DB lookup
        env_query = select(PromptVersion).where(
            PromptVersion.agent_id == agent_id,
            PromptVersion.tenant_id == tenant_id,
            PromptVersion.is_active.is_(True),
            PromptVersion.environment.in_([environment, "all"]),
        ).order_by(PromptVersion.environment.desc())  # "production" > "all"

        result = await self._db.execute(env_query)
        version = result.scalars().first()
        if not version:
            return None

        # Cache it
        try:
            await self._redis.set(
                _cache_key(str(agent_id), environment),
                version.content,
                ex=_CACHE_TTL,
            )
        except Exception as exc:
            logger.warning("prompt_cache_set_error", error=str(exc))

        return version.content

    # ── Diff ─────────────────────────────────────────────────────────────────

    async def get_diff(
        self,
        version_id: uuid.UUID,
        compare_to_id: Optional[uuid.UUID],
        tenant_id: uuid.UUID,
    ) -> str:
        """Return unified diff between two prompt versions."""
        result = await self._db.execute(
            select(PromptVersion).where(
                PromptVersion.id == version_id,
                PromptVersion.tenant_id == tenant_id,
            )
        )
        version = result.scalar_one_or_none()
        if not version:
            raise ValueError(f"Version {version_id} not found")

        if compare_to_id:
            cmp_result = await self._db.execute(
                select(PromptVersion).where(
                    PromptVersion.id == compare_to_id,
                    PromptVersion.tenant_id == tenant_id,
                )
            )
            cmp_version = cmp_result.scalar_one_or_none()
            if not cmp_version:
                raise ValueError(f"Compare version {compare_to_id} not found")
            old_content = cmp_version.content
            old_label = f"v{cmp_version.version_number}"
        else:
            old_content = ""
            old_label = "(empty)"

        diff_lines = list(
            difflib.unified_diff(
                old_content.splitlines(keepends=True),
                version.content.splitlines(keepends=True),
                fromfile=old_label,
                tofile=f"v{version.version_number}",
                lineterm="",
            )
        )
        return "".join(diff_lines)

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _invalidate_cache(self, agent_id: str, environment: str) -> None:
        """Delete all cache entries for this agent (all environments)."""
        for env in ("all", "dev", "staging", "production", environment):
            try:
                await self._redis.delete(_cache_key(agent_id, env))
            except Exception:
                pass
