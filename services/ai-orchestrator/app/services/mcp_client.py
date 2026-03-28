import asyncio
import json
import time
import uuid
from typing import Optional

import httpx
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.core.metrics import TOOL_EXECUTIONS, TOOL_LATENCY, MCP_CIRCUIT_OPENS, CONTEXT_RETRIEVALS, CONTEXT_ITEMS_RETURNED

logger = structlog.get_logger(__name__)


class _MCPCircuitBreaker:
    """Simple circuit breaker for the MCP server."""
    _FAILURE_THRESHOLD = 5
    _COOLDOWN_SECONDS = 30.0

    def __init__(self):
        self._failures = 0
        self._opened_at: Optional[float] = None

    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        if time.monotonic() - self._opened_at >= self._COOLDOWN_SECONDS:
            self._opened_at = None  # transition to HALF_OPEN; allow probe
            return False
        return True

    def on_success(self):
        self._failures = 0
        self._opened_at = None

    def on_failure(self):
        self._failures += 1
        if self._failures >= self._FAILURE_THRESHOLD and self._opened_at is None:
            self._opened_at = time.monotonic()
            MCP_CIRCUIT_OPENS.inc()
            logger.error(
                "mcp_circuit_breaker_opened",
                failures=self._failures,
                cooldown_s=self._COOLDOWN_SECONDS,
            )


class MCPClient:
    """
    HTTP client for communicating with the MCP Server.
    Handles tool execution, context retrieval, and tool schema discovery.
    """

    def __init__(self, base_url: str, ws_url: str):
        self.base_url = base_url.rstrip("/")
        self.ws_url = ws_url.rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None
        self._breaker = _MCPCircuitBreaker()

    async def initialize(self):
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(30.0, connect=5.0),
            headers={"Content-Type": "application/json"},
        )
        logger.info("mcp_client_initialized", base_url=self.base_url)

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
        logger.info("mcp_client_closed")

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("MCPClient not initialized. Call initialize() first.")
        return self._client

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException)),
    )
    async def execute_tool(
        self,
        tenant_id: str,
        tool_name: str,
        parameters: dict,
        session_id: str,
        trace_id: Optional[str] = None,
    ) -> dict:
        """
        Call the MCP Server's /execute endpoint to run a tool.
        Returns the tool result as a dict.
        """
        if trace_id is None:
            trace_id = str(uuid.uuid4())

        payload = {
            "tenant_id": tenant_id,
            "tool_name": tool_name,
            "parameters": parameters,
            "session_id": session_id,
            "trace_id": trace_id,
        }

        if self._breaker.is_open():
            logger.warning("mcp_circuit_open_fast_fail", tool=tool_name)
            TOOL_EXECUTIONS.labels(tool_name=tool_name, status="circuit_open").inc()
            return {"success": False, "error": "MCP service circuit breaker open", "tool_name": tool_name}

        _t0 = time.monotonic()
        try:
            client = self._get_client()
            response = await client.post("/execute", json=payload)
            response.raise_for_status()
            result = response.json()
            self._breaker.on_success()
            TOOL_EXECUTIONS.labels(tool_name=tool_name, status="success").inc()
            TOOL_LATENCY.labels(tool_name=tool_name).observe(time.monotonic() - _t0)
            logger.info(
                "mcp_tool_executed",
                tool=tool_name,
                tenant_id=tenant_id,
                trace_id=trace_id,
                status=response.status_code,
            )
            return result
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code >= 500:
                self._breaker.on_failure()
            TOOL_EXECUTIONS.labels(tool_name=tool_name, status="error").inc()
            TOOL_LATENCY.labels(tool_name=tool_name).observe(time.monotonic() - _t0)
            logger.error(
                "mcp_tool_http_error",
                tool=tool_name,
                status=exc.response.status_code,
            )
            return {
                "success": False,
                "error": f"Tool execution failed with status {exc.response.status_code}",
                "tool_name": tool_name,
            }
        except Exception as exc:
            self._breaker.on_failure()
            TOOL_EXECUTIONS.labels(tool_name=tool_name, status="error").inc()
            TOOL_LATENCY.labels(tool_name=tool_name).observe(time.monotonic() - _t0)
            logger.error("mcp_tool_error", tool=tool_name, error=type(exc).__name__)
            return {
                "success": False,
                "error": str(exc),
                "tool_name": tool_name,
            }

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=5),
        retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException)),
    )
    async def retrieve_context(
        self,
        tenant_id: str,
        query: str,
        session_id: str,
        context_types: list[str] = None,
        knowledge_base_ids: Optional[list[str]] = None,
        top_k: int = 5,
    ) -> list[dict]:
        """
        Call the MCP Server's /context/retrieve endpoint to fetch relevant context
        from knowledge bases and customer history.
        """
        if context_types is None:
            context_types = ["knowledge", "history"]

        payload = {
            "tenant_id": tenant_id,
            "query": query,
            "session_id": session_id,
            "context_types": context_types,
            "top_k": top_k,
        }
        if knowledge_base_ids:
            payload["knowledge_base_ids"] = knowledge_base_ids

        if self._breaker.is_open():
            logger.warning("mcp_circuit_open_context_skip")
            CONTEXT_RETRIEVALS.labels(status="error").inc()
            return []

        try:
            client = self._get_client()
            response = await client.post("/context/retrieve", json=payload)
            response.raise_for_status()
            data = response.json()
            items = data.get("items", data) if isinstance(data, dict) else data
            items = items if isinstance(items, list) else []
            self._breaker.on_success()
            status = "hit" if items else "miss"
            CONTEXT_RETRIEVALS.labels(status=status).inc()
            CONTEXT_ITEMS_RETURNED.observe(len(items))
            logger.info(
                "mcp_context_retrieved",
                tenant_id=tenant_id,
                query_len=len(query),
                items_count=len(items),
            )
            return items
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code >= 500:
                self._breaker.on_failure()
            CONTEXT_RETRIEVALS.labels(status="error").inc()
            logger.warning("mcp_context_http_error", status=exc.response.status_code)
            return []
        except Exception as exc:
            self._breaker.on_failure()
            CONTEXT_RETRIEVALS.labels(status="error").inc()
            logger.warning("mcp_context_error", error=type(exc).__name__)
            return []

    async def list_tools(self, tenant_id: str) -> list[dict]:
        """
        Get the list of tools available for the given tenant.
        """
        try:
            client = self._get_client()
            response = await client.get(
                "/tools",
                params={"tenant_id": tenant_id},
            )
            response.raise_for_status()
            data = response.json()
            tools = data.get("tools", data) if isinstance(data, dict) else data
            return tools if isinstance(tools, list) else []
        except httpx.HTTPStatusError as exc:
            logger.warning("mcp_list_tools_http_error", status=exc.response.status_code)
            return []
        except Exception as exc:
            logger.warning("mcp_list_tools_error", error=str(exc))
            return []

    async def get_tool_schemas(
        self,
        tenant_id: str,
        tool_names: list[str],
    ) -> list[dict]:
        """
        Retrieve OpenAI-compatible function schemas for the specified tools.
        Returns a list of tool schema dicts in the OpenAI tools format:
        [{"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}]
        """
        if not tool_names:
            return []

        try:
            client = self._get_client()
            response = await client.post(
                "/tools/schemas",
                json={"tenant_id": tenant_id, "tool_names": tool_names},
            )
            response.raise_for_status()
            data = response.json()
            schemas = data.get("schemas", data) if isinstance(data, dict) else data
            return schemas if isinstance(schemas, list) else []
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "mcp_tool_schemas_http_error",
                status=exc.response.status_code,
                tool_names=tool_names,
            )
            # Build minimal passthrough schemas so LLM can still call them
            return [
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": f"Execute {name}",
                        "parameters": {
                            "type": "object",
                            "properties": {},
                        },
                    },
                }
                for name in tool_names
            ]
        except Exception as exc:
            logger.warning("mcp_tool_schemas_error", error=str(exc))
            return []

    async def health_check(self) -> bool:
        """Ping the MCP Server health endpoint."""
        try:
            client = self._get_client()
            response = await client.get("/health", timeout=5.0)
            return response.status_code == 200
        except Exception:
            return False
