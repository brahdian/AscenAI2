"""Workflow Registry — converts active workflows into MCP tool definitions.

When an operator activates a workflow, this registry writes/updates a row in
the mcp-server's `mcp_tools` table with:
  name        = "wf:{workflow.id}"
  description = workflow.description   (what the LLM sees as tool description)
  input_schema = workflow.input_schema
  is_builtin  = True
  tool_metadata = {"workflow_id": str(workflow.id)}

The mcp-server's tool_executor then routes wf:* calls to
mcp-server/app/services/workflow_executor.py which creates/advances a
WorkflowExecution via the ai-orchestrator's internal API.

This module runs inside ai-orchestrator and communicates with the mcp-server
via its internal HTTP API (POST /api/v1/tools/upsert-builtin).
"""
from __future__ import annotations

import uuid
from typing import Optional

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.workflow import Workflow

logger = structlog.get_logger(__name__)

_INTERNAL_KEY = getattr(settings, "INTERNAL_API_KEY", "")
_MCP_URL = getattr(settings, "MCP_SERVER_URL", "http://mcp-server:8000")


class WorkflowRegistry:
    """Synchronises active workflow definitions with the mcp-server tool table."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def register(self, workflow: Workflow) -> None:
        """Upsert the wf:<id> tool entry in the mcp-server."""
        tool_name = f"wf:{workflow.id}"
        payload = {
            "name": tool_name,
            "description": workflow.description or f"Workflow: {workflow.name}",
            "category": "workflow",
            "input_schema": workflow.input_schema,
            "is_builtin": True,
            "is_active": True,
            "tool_metadata": {"workflow_id": str(workflow.id)},
            "tenant_id": str(workflow.tenant_id),
        }
        await self._upsert_mcp_tool(payload)
        logger.info("workflow_tool_registered", tool_name=tool_name, workflow_id=str(workflow.id))

    async def deregister(self, workflow: Workflow) -> None:
        """Soft-deactivate the wf:<id> tool entry in the mcp-server."""
        tool_name = f"wf:{workflow.id}"
        payload = {
            "name": tool_name,
            "is_active": False,
            "tenant_id": str(workflow.tenant_id),
        }
        await self._upsert_mcp_tool(payload)
        logger.info("workflow_tool_deregistered", tool_name=tool_name, workflow_id=str(workflow.id))

    async def get_tools_for_tenant(self, tenant_id: uuid.UUID) -> list[dict]:
        """Return all active workflow tool schemas for a given tenant.

        Used by the mcp-server to expand the tool list for LLM calls.
        """
        result = await self.db.execute(
            select(Workflow).where(
                Workflow.tenant_id == tenant_id,
                Workflow.is_active.is_(True),
            )
        )
        workflows = result.scalars().all()
        return [
            {
                "name": f"wf:{wf.id}",
                "description": wf.description,
                "category": "workflow",
                "input_schema": wf.input_schema,
                "tool_metadata": {"workflow_id": str(wf.id)},
            }
            for wf in workflows
        ]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _upsert_mcp_tool(self, payload: dict) -> None:
        """POST to mcp-server /api/v1/tools/upsert-builtin.

        Failures are logged but never raise — tool registration is best-effort.
        The operator can re-activate the workflow to retry.
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    f"{_MCP_URL}/api/v1/tools/upsert-builtin",
                    json=payload,
                    headers={
                        "X-Internal-Key": _INTERNAL_KEY,
                        "Content-Type": "application/json",
                    },
                )
                if resp.status_code not in (200, 201):
                    logger.warning(
                        "workflow_registry_upsert_failed",
                        status=resp.status_code,
                        body=resp.text[:200],
                    )
        except Exception as exc:
            logger.warning("workflow_registry_request_error", error=str(exc))
