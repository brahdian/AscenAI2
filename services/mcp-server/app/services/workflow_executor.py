"""Workflow executor for the MCP server — handles wf:* tool calls.

When the LLM calls a tool whose name starts with "wf:", this module:
  1. Extracts the workflow_id from tool.tool_metadata
  2. Looks up (or creates) a WorkflowExecution for this session
  3. Calls the ai-orchestrator's advance endpoint
  4. Returns the result as a tool response

Communication pattern
---------------------
The mcp-server calls the ai-orchestrator's internal HTTP API:
  POST {AI_ORCHESTRATOR_URL}/api/v1/agents/{agent_id}/flows/{flow_id}/advance

This keeps the execution engine in the ai-orchestrator (which owns the DB
sessions, LLM client, and MCP client) while the mcp-server routes tool calls.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

import httpx
import structlog

from app.core.config import settings

logger = structlog.get_logger(__name__)

_ORCHESTRATOR_URL = settings.AI_ORCHESTRATOR_URL
_INTERNAL_KEY = settings.INTERNAL_API_KEY
_TIMEOUT = 30.0  # seconds — workflow advance may involve LLM calls


async def execute_workflow_tool(
    tool_name: str,
    parameters: dict,
    tool_metadata: dict,
    session_id: str,
    tenant_id: str,
    agent_id: Optional[str] = None,
) -> dict:
    """Entry point called by tool_executor for wf:* tool names.

    Args:
        tool_name:     "wf:appointment_payment" — the full tool name
        parameters:    LLM-provided inputs matching workflow.input_schema
        tool_metadata: {"workflow_id": "uuid-...", "agent_id": "uuid-..."}
        session_id:    The current session identifier
        tenant_id:     Tenant UUID string
        agent_id:      Agent UUID string (may also come from tool_metadata)

    Returns:
        dict with at minimum:
          {"status": "...", "message": "...", "awaiting_input": bool, "context": {...}}
    """
    workflow_id = tool_metadata.get("workflow_id")
    if not workflow_id:
        return {
            "error": f"Tool '{tool_name}' is missing workflow_id in tool_metadata",
            "status": "error",
        }

    # agent_id may come from tool_metadata if not passed directly
    resolved_agent_id = agent_id or tool_metadata.get("agent_id")
    if not resolved_agent_id:
        return {
            "error": f"Tool '{tool_name}' is missing agent_id",
            "status": "error",
        }

    body = {
        "session_id": session_id,
        "event_payload": parameters,  # LLM inputs become initial context
    }

    url = f"{_ORCHESTRATOR_URL}/api/v1/agents/{resolved_agent_id}/flows/{workflow_id}/advance"

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                url,
                json=body,
                headers={
                    "X-Internal-Key": _INTERNAL_KEY,
                    "X-Tenant-ID": str(tenant_id),
                    "Content-Type": "application/json",
                },
            )
            if resp.status_code == 404:
                return {
                    "error": f"Workflow '{tool_name}' not found (workflow_id={workflow_id})",
                    "status": "error",
                }
            if resp.status_code >= 400:
                logger.error(
                    "workflow_advance_failed",
                    tool_name=tool_name,
                    status=resp.status_code,
                    body=resp.text[:300],
                )
                return {
                    "error": f"Workflow execution failed: HTTP {resp.status_code}",
                    "status": "error",
                }

            result: dict = resp.json()
            return _format_result(result)

    except httpx.TimeoutException:
        logger.error("workflow_advance_timeout", tool_name=tool_name, workflow_id=workflow_id)
        return {"error": "Workflow execution timed out.", "status": "error"}
    except Exception as exc:
        logger.error("workflow_advance_error", tool_name=tool_name, error=str(exc))
        return {"error": f"Workflow execution error: {exc}", "status": "error"}


def _format_result(advance_result: dict) -> dict:
    """Normalise WorkflowAdvanceResult into a tool response dict.

    The LLM receives this as the tool output. We include:
    - The message to show the user (if any)
    - The current execution status
    - Whether we're waiting for user input
    - Context variables (for reference)
    """
    status = advance_result.get("status", "UNKNOWN")
    message = advance_result.get("message") or ""
    awaiting = advance_result.get("awaiting_input", False)
    completed = advance_result.get("completed", False)
    error = advance_result.get("error")

    response: dict[str, Any] = {
        "status": status,
        "execution_id": advance_result.get("execution_id"),
        "awaiting_input": awaiting,
        "completed": completed,
    }

    if message:
        response["message"] = message
    if error:
        response["error"] = error

    # Include relevant context keys (not internal _ prefixed ones)
    context = advance_result.get("context", {})
    public_context = {k: v for k, v in context.items() if not k.startswith("_")}
    if public_context:
        response["context"] = public_context

    # Provide a clean summary for the LLM to relay to the user
    if awaiting and message:
        response["next_action"] = f"Ask the user: {message}"
    elif completed and not error:
        response["next_action"] = "Workflow completed. " + (message or "")
    elif error:
        response["next_action"] = f"Workflow failed: {error}"

    return response
