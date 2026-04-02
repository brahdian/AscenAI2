"""
Prompt versioning API.

Endpoints:
  GET    /agents/{agent_id}/prompts                  — list versions
  POST   /agents/{agent_id}/prompts                  — create new version
  GET    /agents/{agent_id}/prompts/{version_id}     — get version detail
  POST   /agents/{agent_id}/prompts/{version_id}/activate   — activate
  POST   /agents/{agent_id}/prompts/{version_id}/rollback   — rollback (alias)
  GET    /agents/{agent_id}/prompts/{version_id}/diff        — unified diff
  GET    /agents/{agent_id}/prompts/ab-tests                 — list A/B tests
  POST   /agents/{agent_id}/prompts/ab-tests                 — create A/B test
  PATCH  /agents/{agent_id}/prompts/ab-tests/{test_id}      — update A/B test
"""
from __future__ import annotations

import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_tenant_db
from app.models.agent import Agent
from app.models.prompt import PromptABTest, PromptVersion
from app.services.prompt_manager import PromptManager

logger = structlog.get_logger(__name__)
router = APIRouter()


def _tenant_id(request: Request) -> str:
    tid = request.headers.get("X-Tenant-ID") or getattr(request.state, "tenant_id", None)
    if not tid:
        raise HTTPException(status_code=401, detail="Tenant ID required.")
    return tid


async def _verify_agent(agent_id: str, tenant_id: str, db: AsyncSession) -> Agent:
    result = await db.execute(
        select(Agent).where(
            Agent.id == uuid.UUID(agent_id),
            Agent.tenant_id == uuid.UUID(tenant_id),
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found.")
    return agent


# ── Request schemas ───────────────────────────────────────────────────────────

class PromptVersionCreate(BaseModel):
    content: str = Field(..., min_length=1)
    environment: str = Field(default="all")
    change_notes: Optional[str] = None
    created_by: Optional[str] = None


class ABTestCreate(BaseModel):
    name: str = Field(..., min_length=1)
    description: Optional[str] = None
    version_a_id: uuid.UUID
    version_b_id: uuid.UUID
    traffic_split_percent: int = Field(default=50, ge=0, le=100)


class ABTestUpdate(BaseModel):
    traffic_split_percent: Optional[int] = Field(None, ge=0, le=100)
    status: Optional[str] = None
    winner_version_id: Optional[uuid.UUID] = None


# ── Version endpoints ─────────────────────────────────────────────────────────

@router.get("/{agent_id}/prompts")
async def list_prompt_versions(
    agent_id: str,
    request: Request,
    environment: Optional[str] = None,
    db: AsyncSession = Depends(get_tenant_db),
):
    tenant_id = _tenant_id(request)
    await _verify_agent(agent_id, tenant_id, db)

    query = select(PromptVersion).where(
        PromptVersion.agent_id == uuid.UUID(agent_id),
        PromptVersion.tenant_id == uuid.UUID(tenant_id),
    )
    if environment:
        query = query.where(PromptVersion.environment == environment)
    query = query.order_by(PromptVersion.version_number.desc())

    result = await db.execute(query)
    return [v.to_dict() for v in result.scalars().all()]


@router.post("/{agent_id}/prompts", status_code=201)
async def create_prompt_version(
    agent_id: str,
    body: PromptVersionCreate,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
):
    """Create a new immutable prompt version (inactive by default)."""
    tenant_id = _tenant_id(request)
    agent = await _verify_agent(agent_id, tenant_id, db)

    from app.core.redis_client import get_redis
    redis = await get_redis()
    mgr = PromptManager(db=db, redis_client=redis)

    version = await mgr.create_version(
        tenant_id=agent.tenant_id,
        agent_id=agent.id,
        content=body.content,
        environment=body.environment,
        change_notes=body.change_notes,
        created_by=body.created_by,
    )
    await db.commit()
    await db.refresh(version)
    logger.info("prompt_version_api_created", agent_id=agent_id, version_id=str(version.id))
    return version.to_dict()


@router.get("/{agent_id}/prompts/{version_id}")
async def get_prompt_version(
    agent_id: str,
    version_id: str,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
):
    tenant_id = _tenant_id(request)
    await _verify_agent(agent_id, tenant_id, db)

    result = await db.execute(
        select(PromptVersion).where(
            PromptVersion.id == uuid.UUID(version_id),
            PromptVersion.agent_id == uuid.UUID(agent_id),
        )
    )
    version = result.scalar_one_or_none()
    if not version:
        raise HTTPException(status_code=404, detail="Prompt version not found.")
    return version.to_dict()


@router.post("/{agent_id}/prompts/{version_id}/activate")
async def activate_prompt_version(
    agent_id: str,
    version_id: str,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
):
    """Activate a prompt version (deactivates any current active version)."""
    tenant_id = _tenant_id(request)
    await _verify_agent(agent_id, tenant_id, db)

    from app.core.redis_client import get_redis
    redis = await get_redis()
    mgr = PromptManager(db=db, redis_client=redis)

    try:
        version = await mgr.activate_version(
            version_id=uuid.UUID(version_id),
            tenant_id=uuid.UUID(tenant_id),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    await db.commit()
    return version.to_dict()


@router.post("/{agent_id}/prompts/{version_id}/rollback")
async def rollback_prompt_version(
    agent_id: str,
    version_id: str,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
):
    """Rollback to a previous prompt version (semantically identical to activate)."""
    return await activate_prompt_version(
        agent_id=agent_id,
        version_id=version_id,
        request=request,
        db=db,
    )


@router.get("/{agent_id}/prompts/{version_id}/diff")
async def get_prompt_diff(
    agent_id: str,
    version_id: str,
    request: Request,
    compare_to: Optional[str] = None,
    db: AsyncSession = Depends(get_tenant_db),
):
    """
    Return a unified diff between this version and another.

    :param compare_to: ID of the version to compare against.
                       If omitted, compares against an empty string (shows full content as added).
    """
    tenant_id = _tenant_id(request)
    await _verify_agent(agent_id, tenant_id, db)

    from app.core.redis_client import get_redis
    redis = await get_redis()
    mgr = PromptManager(db=db, redis_client=redis)

    try:
        diff = await mgr.get_diff(
            version_id=uuid.UUID(version_id),
            compare_to_id=uuid.UUID(compare_to) if compare_to else None,
            tenant_id=uuid.UUID(tenant_id),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return {"diff": diff, "version_id": version_id, "compare_to": compare_to}


# ── A/B Test endpoints ────────────────────────────────────────────────────────

@router.get("/{agent_id}/prompts/ab-tests")
async def list_ab_tests(
    agent_id: str,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
):
    tenant_id = _tenant_id(request)
    await _verify_agent(agent_id, tenant_id, db)

    result = await db.execute(
        select(PromptABTest).where(
            PromptABTest.agent_id == uuid.UUID(agent_id),
            PromptABTest.tenant_id == uuid.UUID(tenant_id),
        ).order_by(PromptABTest.created_at.desc())
    )
    return [t.to_dict() for t in result.scalars().all()]


@router.post("/{agent_id}/prompts/ab-tests", status_code=201)
async def create_ab_test(
    agent_id: str,
    body: ABTestCreate,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
):
    tenant_id = _tenant_id(request)
    agent = await _verify_agent(agent_id, tenant_id, db)

    test = PromptABTest(
        tenant_id=agent.tenant_id,
        agent_id=agent.id,
        name=body.name,
        description=body.description,
        version_a_id=body.version_a_id,
        version_b_id=body.version_b_id,
        traffic_split_percent=body.traffic_split_percent,
    )
    db.add(test)
    await db.commit()
    await db.refresh(test)
    return test.to_dict()


@router.patch("/{agent_id}/prompts/ab-tests/{test_id}")
async def update_ab_test(
    agent_id: str,
    test_id: str,
    body: ABTestUpdate,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
):
    tenant_id = _tenant_id(request)
    await _verify_agent(agent_id, tenant_id, db)

    result = await db.execute(
        select(PromptABTest).where(
            PromptABTest.id == uuid.UUID(test_id),
            PromptABTest.agent_id == uuid.UUID(agent_id),
        )
    )
    test = result.scalar_one_or_none()
    if not test:
        raise HTTPException(status_code=404, detail="A/B test not found.")

    if body.traffic_split_percent is not None:
        test.traffic_split_percent = body.traffic_split_percent
    if body.status is not None:
        test.status = body.status
    if body.winner_version_id is not None:
        test.winner_version_id = body.winner_version_id
        from datetime import datetime, timezone
        test.concluded_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(test)
    return test.to_dict()
