"""
Agent Flows API — CRUD for visual state-machine workflows.

Routes (all under /agents/{agent_id}/flows):
  GET    /                      — list flows
  POST   /                      — create flow
  GET    /{flow_id}             — get flow
  PUT    /{flow_id}             — full update (steps + ui_layout)
  PATCH  /{flow_id}             — partial update
  DELETE /{flow_id}             — delete
  POST   /{flow_id}/activate    — make active (deactivates others)
  GET    /{flow_id}/execution/{session_id}  — live execution state
"""
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_tenant
from app.models.agent import Agent, AgentFlow

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class FlowCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    trigger_keywords: List[str] = Field(default_factory=list)
    initial_step_id: Optional[str] = None
    steps: Dict[str, Any] = Field(default_factory=dict)
    ui_layout: Dict[str, Any] = Field(default_factory=dict)


class FlowUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    trigger_keywords: Optional[List[str]] = None
    initial_step_id: Optional[str] = None
    steps: Optional[Dict[str, Any]] = None
    ui_layout: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_agent(agent_id: str, tenant_id: uuid.UUID, db: AsyncSession) -> Agent:
    result = await db.execute(
        select(Agent).where(
            Agent.id == uuid.UUID(agent_id),
            Agent.tenant_id == tenant_id,
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


async def _get_flow(
    flow_id: str, agent_id: str, tenant_id: uuid.UUID, db: AsyncSession
) -> AgentFlow:
    result = await db.execute(
        select(AgentFlow).where(
            AgentFlow.id == uuid.UUID(flow_id),
            AgentFlow.agent_id == uuid.UUID(agent_id),
            AgentFlow.tenant_id == tenant_id,
        )
    )
    flow = result.scalar_one_or_none()
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")
    return flow


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/{agent_id}/flows")
async def list_flows(
    agent_id: str,
    tenant=Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    await _get_agent(agent_id, tenant.id, db)
    result = await db.execute(
        select(AgentFlow)
        .where(AgentFlow.agent_id == uuid.UUID(agent_id), AgentFlow.tenant_id == tenant.id)
        .order_by(AgentFlow.created_at.desc())
    )
    return [f.to_dict() for f in result.scalars().all()]


@router.post("/{agent_id}/flows", status_code=status.HTTP_201_CREATED)
async def create_flow(
    agent_id: str,
    body: FlowCreate,
    tenant=Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    await _get_agent(agent_id, tenant.id, db)
    flow = AgentFlow(
        agent_id=uuid.UUID(agent_id),
        tenant_id=tenant.id,
        name=body.name,
        description=body.description,
        trigger_keywords=body.trigger_keywords,
        initial_step_id=body.initial_step_id,
        steps=body.steps,
        ui_layout=body.ui_layout,
    )
    db.add(flow)
    await db.commit()
    await db.refresh(flow)
    return flow.to_dict()


@router.get("/{agent_id}/flows/{flow_id}")
async def get_flow(
    agent_id: str,
    flow_id: str,
    tenant=Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    flow = await _get_flow(flow_id, agent_id, tenant.id, db)
    return flow.to_dict()


@router.put("/{agent_id}/flows/{flow_id}")
async def update_flow(
    agent_id: str,
    flow_id: str,
    body: FlowCreate,
    tenant=Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    flow = await _get_flow(flow_id, agent_id, tenant.id, db)
    flow.name = body.name
    flow.description = body.description
    flow.trigger_keywords = body.trigger_keywords
    flow.initial_step_id = body.initial_step_id
    flow.steps = body.steps
    flow.ui_layout = body.ui_layout
    flow.version = (flow.version or 1) + 1
    await db.commit()
    await db.refresh(flow)
    return flow.to_dict()


@router.patch("/{agent_id}/flows/{flow_id}")
async def patch_flow(
    agent_id: str,
    flow_id: str,
    body: FlowUpdate,
    tenant=Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    flow = await _get_flow(flow_id, agent_id, tenant.id, db)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(flow, field, value)
    if body.steps is not None or body.name is not None:
        flow.version = (flow.version or 1) + 1
    await db.commit()
    await db.refresh(flow)
    return flow.to_dict()


@router.delete("/{agent_id}/flows/{flow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_flow(
    agent_id: str,
    flow_id: str,
    tenant=Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    flow = await _get_flow(flow_id, agent_id, tenant.id, db)
    await db.delete(flow)
    await db.commit()


@router.post("/{agent_id}/flows/{flow_id}/activate")
async def activate_flow(
    agent_id: str,
    flow_id: str,
    tenant=Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Activate this flow and deactivate all others for this agent."""
    flow = await _get_flow(flow_id, agent_id, tenant.id, db)
    # Deactivate all flows for this agent
    await db.execute(
        update(AgentFlow)
        .where(AgentFlow.agent_id == uuid.UUID(agent_id), AgentFlow.tenant_id == tenant.id)
        .values(is_active=False)
    )
    flow.is_active = True
    await db.commit()
    await db.refresh(flow)
    return flow.to_dict()


@router.get("/{agent_id}/flows/{flow_id}/execution/{session_id}")
async def get_execution_state(
    agent_id: str,
    flow_id: str,
    session_id: str,
    tenant=Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """
    Return the live PlaybookEngine state for a session running this flow.
    Reads from Redis (fast path) then falls back to DB checkpoint.
    """
    from app.models.agent import PlaybookExecution
    from app.core.redis_client import get_redis
    import json

    # Validate flow exists
    await _get_flow(flow_id, agent_id, tenant.id, db)

    # Try Redis first
    try:
        redis = await get_redis()
        key = f"pb_state:{session_id}:{flow_id}"
        raw = await redis.get(key)
        if raw:
            state = json.loads(raw)
            return {
                "session_id": session_id,
                "flow_id": flow_id,
                "source": "redis",
                **state,
            }
    except Exception:
        pass

    # Fall back to DB
    result = await db.execute(
        select(PlaybookExecution).where(
            PlaybookExecution.session_id == session_id,
            PlaybookExecution.playbook_id == flow_id,
            PlaybookExecution.tenant_id == tenant.id,
        )
    )
    exec_row = result.scalar_one_or_none()
    if not exec_row:
        return {
            "session_id": session_id,
            "flow_id": flow_id,
            "source": "none",
            "status": "not_started",
            "current_step_id": None,
            "variables": {},
            "history": [],
            "step_count": 0,
        }

    return {
        "session_id": session_id,
        "flow_id": flow_id,
        "source": "db",
        "status": exec_row.status,
        "current_step_id": exec_row.current_step_id,
        "variables": exec_row.variables or {},
        "history": exec_row.history or [],
        "step_count": exec_row.step_count,
        "error_message": exec_row.error_message,
        "created_at": exec_row.created_at.isoformat() if exec_row.created_at else None,
        "updated_at": exec_row.updated_at.isoformat() if exec_row.updated_at else None,
    }
