from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.mcp import ExecutionResponse, MCPToolCall, MCPToolResult
from app.services.tool_executor import ToolExecutor
from app.services.tool_registry import ToolRegistry

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/execute")


def _tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None)
    if not tid:
        raise HTTPException(status_code=401, detail="Tenant ID required.")
    return tid


async def _tenant_db(
    tenant_id: str = Depends(_tenant_id),
):
    async for session in get_db(tenant_id):
        yield session


def _get_redis(request: Request):
    return getattr(request.app.state, "redis", None)


@router.post("", response_model=MCPToolResult)
async def execute_tool(
    body: MCPToolCall,
    request: Request,
    tenant_id: str = Depends(_tenant_id),
    db: AsyncSession = Depends(_tenant_db),
):
    """Execute a tool call and return the result."""
    redis = _get_redis(request)
    executor = ToolExecutor(db=db, redis=redis)

    try:
        result = await executor.execute(tenant_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return result


@router.get("/history", response_model=list[ExecutionResponse])
async def execution_history(
    request: Request,
    session_id: str | None = None,
    limit: int = 50,
    tenant_id: str = Depends(_tenant_id),
    db: AsyncSession = Depends(_tenant_db),
):
    """Get tool execution history for the tenant."""
    from sqlalchemy import select
    from app.models.tool import ToolExecution
    import uuid

    query = (
        select(ToolExecution)
        .where(ToolExecution.tenant_id == uuid.UUID(tenant_id))
        .order_by(ToolExecution.created_at.desc())
        .limit(min(limit, 200))
    )

    if session_id:
        query = query.where(ToolExecution.session_id == session_id)

    result = await db.execute(query)
    executions = result.scalars().all()
    return executions
