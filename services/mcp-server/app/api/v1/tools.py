from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.mcp import ToolRegistration, ToolResponse, ToolUpdate
from app.services.tool_registry import ToolRegistry

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/tools")


def _tenant_id(request: Request) -> str:
    tid = request.headers.get("X-Tenant-ID") or getattr(request.state, "tenant_id", None)
    if not tid:
        raise HTTPException(status_code=401, detail="Tenant ID required.")
    return tid


@router.post("", response_model=ToolResponse, status_code=201)
async def register_tool(
    body: ToolRegistration,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Register a new tool for the tenant."""
    tenant_id = _tenant_id(request)
    registry = ToolRegistry(db)
    try:
        tool = await registry.register_tool(tenant_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await db.commit()
    await db.refresh(tool)
    return tool


@router.get("", response_model=list[ToolResponse])
async def list_tools(
    request: Request,
    category: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """List all active tools for the tenant."""
    tenant_id = _tenant_id(request)
    registry = ToolRegistry(db)
    return await registry.list_tools(tenant_id, category=category)


@router.get("/{tool_name}", response_model=ToolResponse)
async def get_tool(
    tool_name: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Get a specific tool by name."""
    tenant_id = _tenant_id(request)
    registry = ToolRegistry(db)
    tool = await registry.get_tool(tenant_id, tool_name)
    if not tool:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found.")
    return tool


@router.patch("/{tool_name}", response_model=ToolResponse)
async def update_tool(
    tool_name: str,
    body: ToolUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Update a tool's configuration."""
    tenant_id = _tenant_id(request)
    registry = ToolRegistry(db)
    try:
        tool = await registry.update_tool(tenant_id, tool_name, body)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    await db.commit()
    await db.refresh(tool)
    return tool


@router.delete("/{tool_name}", status_code=204)
async def delete_tool(
    tool_name: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Delete (deactivate) a tool."""
    tenant_id = _tenant_id(request)
    registry = ToolRegistry(db)
    try:
        await registry.delete_tool(tenant_id, tool_name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    await db.commit()
