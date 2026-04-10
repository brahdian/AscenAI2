import uuid
from typing import Optional, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_tenant_db
from app.models.agent import Agent
from app.models.variable import AgentVariable

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


class VariableCreate(BaseModel):
    name: str
    description: Optional[str] = None
    scope: str = "global"  # 'global' or 'local'
    data_type: str = "string"  # 'string', 'number', 'boolean', 'object'
    default_value: Optional[Any] = None
    playbook_id: Optional[str] = None
    is_secret: bool = False


class VariableUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    scope: Optional[str] = None
    data_type: Optional[str] = None
    default_value: Optional[Any] = None
    playbook_id: Optional[str] = None
    is_secret: Optional[bool] = None


@router.get("/{agent_id}/variables")
async def list_variables(
    agent_id: str,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
) -> list[dict]:
    tenant_id = _tenant_id(request)
    await _verify_agent(agent_id, tenant_id, db)

    result = await db.execute(
        select(AgentVariable).where(AgentVariable.agent_id == uuid.UUID(agent_id))
    )
    variables = result.scalars().all()
    return [v.to_dict() for v in variables]


@router.post("/{agent_id}/variables", status_code=201)
async def create_variable(
    agent_id: str,
    payload: VariableCreate,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    tenant_id = _tenant_id(request)
    agent = await _verify_agent(agent_id, tenant_id, db)

    # Check for name collision
    existing = await db.execute(
        select(AgentVariable).where(
            AgentVariable.agent_id == agent.id,
            AgentVariable.name == payload.name,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Variable with this name already exists.")

    playbook_uuid = uuid.UUID(payload.playbook_id) if payload.playbook_id else None

    var = AgentVariable(
        id=uuid.uuid4(),
        agent_id=agent.id,
        tenant_id=agent.tenant_id,
        playbook_id=playbook_uuid,
        name=payload.name,
        description=payload.description,
        scope=payload.scope,
        data_type=payload.data_type,
        default_value=payload.default_value,
        is_secret=payload.is_secret,
    )
    db.add(var)
    await db.commit()
    await db.refresh(var)

    return var.to_dict()


@router.put("/{agent_id}/variables/{variable_id}")
async def update_variable(
    agent_id: str,
    variable_id: str,
    payload: VariableUpdate,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    tenant_id = _tenant_id(request)
    await _verify_agent(agent_id, tenant_id, db)

    result = await db.execute(
        select(AgentVariable).where(
            AgentVariable.id == uuid.UUID(variable_id),
            AgentVariable.agent_id == uuid.UUID(agent_id),
        )
    )
    var = result.scalar_one_or_none()
    if not var:
        raise HTTPException(status_code=404, detail="Variable not found.")

    if payload.name is not None and payload.name != var.name:
        # Check name collision
        existing = await db.execute(
            select(AgentVariable).where(
                AgentVariable.agent_id == uuid.UUID(agent_id),
                AgentVariable.name == payload.name,
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Variable with this name already exists.")
        var.name = payload.name

    if payload.description is not None:
        var.description = payload.description
    if payload.scope is not None:
        var.scope = payload.scope
    if payload.default_value is not None:
        var.default_value = payload.default_value
    if payload.playbook_id is not None:
        var.playbook_id = uuid.UUID(payload.playbook_id) if payload.playbook_id else None
    if payload.is_secret is not None:
        var.is_secret = payload.is_secret

    await db.commit()
    await db.refresh(var)

    return var.to_dict()


@router.delete("/{agent_id}/variables/{variable_id}")
async def delete_variable(
    agent_id: str,
    variable_id: str,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
):
    tenant_id = _tenant_id(request)
    await _verify_agent(agent_id, tenant_id, db)

    result = await db.execute(
        select(AgentVariable).where(
            AgentVariable.id == uuid.UUID(variable_id),
            AgentVariable.agent_id == uuid.UUID(agent_id),
        )
    )
    var = result.scalar_one_or_none()
    if not var:
        raise HTTPException(status_code=404, detail="Variable not found.")

    await db.delete(var)
    await db.commit()
    return {"message": "Variable deleted"}
