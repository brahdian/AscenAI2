"""
agent_call — invoke another agent by ID or name.

This tool allows an AI agent to delegate a task to another specialized agent.
The called agent processes the input and returns its response.
"""
from __future__ import annotations
import httpx
import structlog

logger = structlog.get_logger(__name__)

TOOL_DEFINITION = {
    "name": "agent_call",
    "description": (
        "Invoke another AI agent by its ID or name to handle a specialized task. "
        "Use this to delegate to a specialized agent (e.g., billing agent, tech support agent). "
        "Returns the agent's text response."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "agent_id": {
                "type": "string",
                "description": "The UUID of the agent to call",
            },
            "message": {
                "type": "string",
                "description": "The message or task to send to the agent",
            },
            "context": {
                "type": "string",
                "description": "Optional additional context about the caller or situation",
                "default": "",
            },
        },
        "required": ["agent_id", "message"],
    },
}


async def execute(
    agent_id: str,
    message: str,
    context: str = "",
    tenant_id: str = "",
    orchestrator_url: str = "http://ai-orchestrator:8002",
    **_kwargs,
) -> dict:
    """Call another agent and return its response."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{orchestrator_url}/api/v1/chat/agent-call",
                json={
                    "agent_id": agent_id,
                    "message": message,
                    "context": context,
                    "tenant_id": tenant_id,
                },
                headers={"X-Tenant-ID": tenant_id} if tenant_id else {},
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "success": True,
                "response": data.get("response", ""),
                "agent_id": agent_id,
            }
    except httpx.HTTPError as e:
        logger.error("agent_call_failed", agent_id=agent_id, error=str(e))
        return {"success": False, "error": f"Failed to reach agent: {e}", "agent_id": agent_id}


async def handle_agent_call(parameters: dict, config: dict) -> dict:
    """Built-in handler wrapper for ToolExecutor."""
    agent_id = parameters.get("agent_id", "")
    message = parameters.get("message", "")
    context = parameters.get("context", "")
    tenant_id = config.get("tenant_id", "")
    orchestrator_url = config.get("orchestrator_url", "http://ai-orchestrator:8002")
    return await execute(
        agent_id=agent_id,
        message=message,
        context=context,
        tenant_id=tenant_id,
        orchestrator_url=orchestrator_url,
    )
