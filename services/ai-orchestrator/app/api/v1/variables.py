import csv
import io
import re
import uuid
import bleach
from typing import Any, Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_tenant_db, require_internal_key
from app.models.agent import Agent
from app.models.variable import AgentVariable
from app.core.zenith import ZenithContext, get_zenith_context
from app.core.rate_limiter import RateLimiter
from app.services import pii_service

logger = structlog.get_logger(__name__)

router = APIRouter()

# Maximum number of variables allowed per agent (prevents system-prompt bloat)
_MAX_VARIABLES_PER_AGENT = 50

_VALID_TYPES = {"string", "number", "boolean", "object"}
_VALID_SCOPES = {"global", "local"}


def _tenant_id(request: Request) -> str:
    tid = request.headers.get("X-Tenant-ID") or getattr(request.state, "tenant_id", None)
    if not tid:
        raise HTTPException(status_code=401, detail="Tenant ID required.")
    return tid


async def _invalidate_cache(agent_id: str):
    """Triggered after variable mutations to clear stale Redis context."""
    try:
        from app.core.redis_client import get_redis
        redis = await get_redis()
        if not redis:
            return
        # Invalidate both global and any per-playbook cache entries
        async for key in redis.scan_iter(f"agent_variables:{agent_id}:*"):
            await redis.delete(key)
    except Exception:
        # Fail silent for cache ops to prioritize DB transaction Success
        pass


async def _verify_agent(agent_id: str, tenant_id: str, db: AsyncSession, request: Request | None = None) -> Agent:
    raid = None
    if request:
        raid_str = request.headers.get("X-Restricted-Agent-ID")
        if raid_str:
            try:
                raid = uuid.UUID(raid_str)
            except ValueError: pass

    # Apply isolation (CRIT-005)
    if raid and uuid.UUID(agent_id) != raid:
        raise HTTPException(status_code=404, detail="Agent not found.")

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


def _validate_value_type(data_type: str, value: Any) -> None:
    if data_type not in _VALID_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid data type: {data_type}. Must be one of {_VALID_TYPES}")
    
    if value is None:
        return
    if data_type == "number":
        if not isinstance(value, (int, float)):
            raise HTTPException(status_code=400, detail="Value must be a number.")
    elif data_type == "boolean":
        if not isinstance(value, bool):
            raise HTTPException(status_code=400, detail="Value must be a boolean.")
    elif data_type == "object":
        if not isinstance(value, dict):
            raise HTTPException(status_code=400, detail="Value must be a JSON object.")
    elif data_type == "string":
        if not isinstance(value, str):
            raise HTTPException(status_code=400, detail="Value must be a string.")


class VariableCreate(BaseModel):
    name: str = Field(..., pattern=r"^[a-zA-Z][a-zA-Z0-9_]*$", max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    scope: Literal["global", "local"] = "global"
    data_type: Literal["string", "number", "boolean", "object"] = "string"
    default_value: Optional[Any] = None
    playbook_id: Optional[str] = None
    is_secret: bool = False

    @field_validator("description")
    @classmethod
    def sanitize_description(cls, v: Any) -> Any:
        if v is None:
            return v
        return bleach.clean(v, tags=[], attributes={}, styles=[], strip=True)

    @field_validator("default_value")
    @classmethod
    def validate_value_size(cls, v: Any) -> Any:
        if v is None:
            return v
        # Limit total stringified size to 10k to prevent prompt-bloat attacks
        s = str(v)
        if len(s) > 10000:
            raise ValueError("Variable value is too large (max 10,000 characters).")
        return v


class VariableUpdate(BaseModel):
    name: Optional[str] = Field(None, pattern=r"^[a-zA-Z][a-zA-Z0-9_]*$", max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    scope: Optional[Literal["global", "local"]] = None
    data_type: Optional[Literal["string", "number", "boolean", "object"]] = None
    default_value: Optional[Any] = None
    playbook_id: Optional[str] = None
    is_secret: Optional[bool] = None

    @field_validator("description")
    @classmethod
    def sanitize_description(cls, v: Any) -> Any:
        if v is None:
            return v
        return bleach.clean(v, tags=[], attributes={}, styles=[], strip=True)

    @field_validator("default_value")
    @classmethod
    def validate_value_size(cls, v: Any) -> Any:
        if v is None:
            return v
        s = str(v)
        if len(s) > 10000:
            raise ValueError("Variable value is too large (max 10,000 characters).")
        return v


@router.get("/{agent_id}/variables")
async def list_variables(
    agent_id: str,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
    z_ctx: ZenithContext = Depends(get_zenith_context),
    _internal: bool = Depends(require_internal_key),
) -> list[dict]:
    """
    List all variables for an agent with mandatory deterministic sorting (Zenith Pillar 1).
    """
    await _verify_agent(agent_id, z_ctx.tenant_id, db, request=request)

    result = await db.execute(
        select(AgentVariable)
        .where(AgentVariable.agent_id == uuid.UUID(agent_id))
        .order_by(AgentVariable.created_at.desc(), AgentVariable.id.desc())
    )
    variables = result.scalars().all()
    return [v.to_dict() for v in variables]


@router.get("/{agent_id}/variables/export")
async def export_variables(
    agent_id: str,
    request: Request,
    justification_id: str,
    db: AsyncSession = Depends(get_tenant_db),
    z_ctx: ZenithContext = Depends(get_zenith_context),
):
    """
    Zenith Pillar 2: Forensic Data Export with Justification & Sanitization.
    """
    if not justification_id:
        raise HTTPException(status_code=400, detail="justification_id is required for forensic exports.")

    # Rate Limiting
    limiter = RateLimiter(request.app.state.redis)
    if not await limiter.is_allowed(f"var_export:{z_ctx.tenant_id}", limit=5, window_seconds=60):
        raise HTTPException(status_code=429, detail="Export rate limit exceeded. Please wait.")

    await _verify_agent(agent_id, z_ctx.tenant_id, db, request=request)

    result = await db.execute(
        select(AgentVariable)
        .where(AgentVariable.agent_id == uuid.UUID(agent_id))
        .order_by(AgentVariable.created_at.desc(), AgentVariable.id.desc())
    )
    variables = result.scalars().all()

    # Zenith Logging
    logger.info(
        "variables_exported",
        agent_id=agent_id,
        tenant_id=z_ctx.tenant_id,
        actor_email=z_ctx.actor_email,
        is_support_access=z_ctx.is_support_access,
        justification_id=justification_id,
        trace_id=z_ctx.trace_id,
        record_count=len(variables),
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID", "Name", "Description", "Scope", "Data Type", "Default Value", 
        "Is Secret", "Created At", "Updated At"
    ])

    def sanitize_csv(val: Any) -> str:
        s = str(val) if val is not None else ""
        if s and s[0] in ('=', '+', '-', '@'):
            return f"'{s}"
        return s

    for var in variables:
        d = var.to_dict(redact_secrets=True)
        writer.writerow([
            d["id"],
            sanitize_csv(d["name"]),
            sanitize_csv(d["description"]),
            sanitize_csv(d["scope"]),
            sanitize_csv(d["data_type"]),
            sanitize_csv(d["default_value"]),
            d["is_secret"],
            d["created_at"],
            d["updated_at"]
        ])

    writer.writerow(["# END OF AUDIT EXPORT #"])

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="variables_audit_{agent_id}.csv"'
        }
    )

@router.post("/{agent_id}/variables", status_code=201)
async def create_variable(
    agent_id: str,
    payload: VariableCreate,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
    z_ctx: ZenithContext = Depends(get_zenith_context),
    _internal: bool = Depends(require_internal_key),
) -> dict:
    # Pillar 4: Redis-backed Rate Limiting
    limiter = RateLimiter(request.app.state.redis)
    if not await limiter.is_allowed(f"var_mutation:{z_ctx.tenant_id}", limit=20, window_seconds=60):
        logger.warning("rate_limit_exceeded_variable_mutation", tenant_id=z_ctx.tenant_id)
        raise HTTPException(status_code=429, detail="Rate limit exceeded for variable mutations. Please wait.")

    agent = await _verify_agent(agent_id, z_ctx.tenant_id, db, request=request)

    # Validate value vs type
    _validate_value_type(payload.data_type, payload.default_value)

    # Check for name collision
    existing = await db.execute(
        select(AgentVariable).where(
            AgentVariable.agent_id == agent.id,
            AgentVariable.name == payload.name,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Variable with this name already exists.")

    # Enforce a per-agent variable limit
    count_res = await db.execute(
        select(func.count()).where(AgentVariable.agent_id == agent.id)
    )
    if (count_res.scalar() or 0) >= _MAX_VARIABLES_PER_AGENT:
        raise HTTPException(
            status_code=400,
            detail=f"Variable limit reached ({_MAX_VARIABLES_PER_AGENT} variables per agent).",
        )

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
    try:
        db.add(var)
        await db.commit()
        await db.refresh(var)
    except Exception as e:
        logger.error("variable_create_failed", error=str(e), trace_id=z_ctx.trace_id)
        raise HTTPException(
            status_code=500,
            detail=f"An internal error occurred. Trace ID: {z_ctx.trace_id}"
        )

    await _invalidate_cache(agent_id)

    # Zenith Pillar 1: Actor Signature Forensic Logging
    logger.info(
        "variable_created",
        agent_id=agent_id,
        tenant_id=z_ctx.tenant_id,
        actor_email=z_ctx.actor_email,
        is_support_access=z_ctx.is_support_access,
        trace_id=z_ctx.trace_id,
        variable_name=payload.name,
        scope=payload.scope,
        data_type=payload.data_type,
        is_secret=payload.is_secret,
    )

    return var.to_dict()


@router.put("/{agent_id}/variables/{variable_id}")
async def update_variable(
    agent_id: str,
    variable_id: str,
    payload: VariableUpdate,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
    z_ctx: ZenithContext = Depends(get_zenith_context),
    _internal: bool = Depends(require_internal_key),
) -> dict:
    # Pillar 4: Redis-backed Rate Limiting
    limiter = RateLimiter(request.app.state.redis)
    if not await limiter.is_allowed(f"var_mutation:{z_ctx.tenant_id}", limit=20, window_seconds=60):
        raise HTTPException(status_code=429, detail="Rate limit exceeded.")

    await _verify_agent(agent_id, z_ctx.tenant_id, db, request=request)

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
        existing = await db.execute(
            select(AgentVariable).where(
                AgentVariable.agent_id == uuid.UUID(agent_id),
                AgentVariable.name == payload.name,
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Variable with this name already exists.")
        var.name = payload.name

    eff_default = payload.default_value
    explicit_clear = (
        "default_value" in payload.model_fields_set
        and payload.default_value is None
    )
    if var.is_secret and eff_default == "***":
        eff_default = None  # Signal: No change to default_value
        explicit_clear = False

    if var.is_secret and payload.is_secret is False:
        if (payload.default_value is None and not explicit_clear) or payload.default_value == "***":
            raise HTTPException(
                status_code=400,
                detail="Must provide a new value when removing secret protection."
            )

    # Validate value vs type if either is changing
    new_type = payload.data_type or var.data_type
    if eff_default is not None:
        _validate_value_type(new_type, eff_default)
    elif payload.data_type is not None and not explicit_clear:
        _validate_value_type(new_type, var.default_value)

    if payload.description is not None:
        var.description = payload.description
    if payload.scope is not None:
        var.scope = payload.scope
    if payload.data_type is not None:
        var.data_type = payload.data_type
    if explicit_clear:
        var.default_value = None
    elif eff_default is not None:
        var.default_value = eff_default
    if payload.playbook_id is not None:
        var.playbook_id = uuid.UUID(payload.playbook_id) if payload.playbook_id else None
    if payload.is_secret is not None:
        var.is_secret = payload.is_secret

    try:
        await db.commit()
        await db.refresh(var)
    except Exception as e:
        logger.error("variable_update_failed", error=str(e), trace_id=z_ctx.trace_id)
        raise HTTPException(
            status_code=500,
            detail=f"An internal error occurred. Trace ID: {z_ctx.trace_id}"
        )

    await _invalidate_cache(agent_id)

    # Zenith Pillar 1: Actor Signature Forensic Logging
    logger.info(
        "variable_updated",
        agent_id=agent_id,
        tenant_id=z_ctx.tenant_id,
        actor_email=z_ctx.actor_email,
        is_support_access=z_ctx.is_support_access,
        trace_id=z_ctx.trace_id,
        variable_id=variable_id,
        variable_name=var.name,
        is_secret=var.is_secret,
    )

    return var.to_dict()


@router.delete("/{agent_id}/variables/{variable_id}")
async def delete_variable(
    agent_id: str,
    variable_id: str,
    request: Request,
    db: AsyncSession = Depends(get_tenant_db),
    z_ctx: ZenithContext = Depends(get_zenith_context),
):
    # Pillar 4: Redis-backed Rate Limiting
    limiter = RateLimiter(request.app.state.redis)
    if not await limiter.is_allowed(f"var_mutation:{z_ctx.tenant_id}", limit=20, window_seconds=60):
        raise HTTPException(status_code=429, detail="Rate limit exceeded.")

    await _verify_agent(agent_id, z_ctx.tenant_id, db, request=request)

    result = await db.execute(
        select(AgentVariable).where(
            AgentVariable.id == uuid.UUID(variable_id),
            AgentVariable.agent_id == uuid.UUID(agent_id),
        )
    )
    var = result.scalar_one_or_none()
    if not var:
        raise HTTPException(status_code=404, detail="Variable not found.")

    variable_name = var.name
    is_secret = var.is_secret
    await db.delete(var)
    await db.commit()

    await _invalidate_cache(agent_id)

    # Zenith Pillar 1: Actor Signature Forensic Logging
    logger.info(
        "variable_deleted",
        agent_id=agent_id,
        tenant_id=z_ctx.tenant_id,
        actor_email=z_ctx.actor_email,
        is_support_access=z_ctx.is_support_access,
        trace_id=z_ctx.trace_id,
        variable_id=variable_id,
        variable_name=variable_name,
        is_secret=is_secret,
    )

    return {"message": "Variable deleted"}
