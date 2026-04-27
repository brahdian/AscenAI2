import asyncio
import json
import re
import time
import uuid
from typing import Optional

import httpx
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.core.config import settings
from shared.internal_auth import generate_internal_token
from app.core.metrics import (
    CONTEXT_RETRIEVALS,
    CONTEXT_ITEMS_RETURNED,
    TOOL_EXECUTIONS,
    TOOL_LATENCY,
    MCP_CIRCUIT_OPENS,
)

logger = structlog.get_logger(__name__)

# ── Redis-backed circuit breaker constants ────────────────────────────────────
# These keys live in Redis so state is shared across all Uvicorn workers.
_CB_FAIL_PREFIX = "mcp:cb:failures:"      # Redis INCR key per host endpoint
_CB_OPEN_PREFIX = "mcp:cb:opened_at:"     # Redis string set when breaker opens
_CB_FAILURE_THRESHOLD = 5
_CB_COOLDOWN_SECONDS = 30
_CB_FAILURE_TTL = 120  # seconds — auto-expire failure counter after inactivity

# ── Idempotency classification ────────────────────────────────────────────────
# Tools whose names match these patterns execute write/side-effect operations
# and MUST NOT be retried on timeout (partial execution already happened).
_NON_IDEMPOTENT_PATTERN = re.compile(
    r"(charge|pay|book|reserve|order|send|submit|create|delete|cancel|"
    r"refund|debit|transfer|enroll|register|post|publish|deploy|push)",
    re.IGNORECASE,
)

TOOL_EXECUTION_TIMEOUT_SECONDS = 15.0  # Hard timeout per tool call


def _is_idempotent(tool_name: str) -> bool:
    """Return False for tools that mutate state and must not be retried blindly."""
    return not bool(_NON_IDEMPOTENT_PATTERN.search(tool_name))


class _RedisCircuitBreaker:
    """Redis-backed circuit breaker — safe across multiple workers/processes."""

    def __init__(self, redis_client, endpoint_key: str):
        self._redis = redis_client
        self._fail_key = f"{_CB_FAIL_PREFIX}{endpoint_key}"
        self._open_key = f"{_CB_OPEN_PREFIX}{endpoint_key}"

    async def is_open(self) -> bool:
        opened_raw = await self._redis.get(self._open_key)
        if not opened_raw:
            return False
        opened_at = float(opened_raw)
        if time.monotonic() - opened_at >= _CB_COOLDOWN_SECONDS:
            # Cooldown elapsed — delete the open marker to go HALF-OPEN
            await self._redis.delete(self._open_key)
            return False
        return True

    async def on_success(self):
        await self._redis.delete(self._fail_key)
        await self._redis.delete(self._open_key)

    async def on_failure(self):
        count = await self._redis.incr(self._fail_key)
        await self._redis.expire(self._fail_key, _CB_FAILURE_TTL)
        if int(count) >= _CB_FAILURE_THRESHOLD:
            # Transition to OPEN only once (set NX so concurrent workers don't race)
            opened = await self._redis.set(
                self._open_key, str(time.monotonic()), nx=True, ex=_CB_COOLDOWN_SECONDS + 10
            )
            if opened:
                MCP_CIRCUIT_OPENS.inc()
                logger.error(
                    "mcp_circuit_breaker_opened",
                    failures=count,
                    cooldown_s=_CB_COOLDOWN_SECONDS,
                )


class MCPClient:
    """
    HTTP client for communicating with the MCP Server.
    Handles tool execution, context retrieval, and tool schema discovery.
    """

    def __init__(self, base_url: str, ws_url: str, redis_client=None):
        self.base_url = base_url.rstrip("/")
        self.ws_url = ws_url.rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None
        self._regional_clients: dict[str, httpx.AsyncClient] = {}
        self._redis = redis_client
        # Lazy-init circuit breaker — requires redis to be set via set_redis()
        self._breaker: Optional[_RedisCircuitBreaker] = None

    def set_redis(self, redis_client) -> None:
        """Inject the shared Redis client. Must be called before first use."""
        self._redis = redis_client
        self._breaker = _RedisCircuitBreaker(redis_client, endpoint_key="mcp_execute")
        self._context_breaker = _RedisCircuitBreaker(redis_client, endpoint_key="mcp_context")

    async def initialize(self):
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(TOOL_EXECUTION_TIMEOUT_SECONDS + 5.0, connect=5.0),
            headers={"Content-Type": "application/json"},
        )
        
        # Phase 6: Initialize regional shards
        regional_configs = {
            "us": settings.MCP_SERVER_URL_US,
            "eu": settings.MCP_SERVER_URL_EU
        }
        for region, url in regional_configs.items():
            if url:
                self._regional_clients[region] = httpx.AsyncClient(
                    base_url=url.rstrip("/"),
                    timeout=httpx.Timeout(10.0, connect=3.0),
                    headers={"Content-Type": "application/json"},
                )
        
        logger.info("mcp_client_initialized", base_url=self.base_url, shards=list(self._regional_clients.keys()))

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
        for client in self._regional_clients.values():
            await client.aclose()
        self._regional_clients.clear()
        logger.info("mcp_client_closed")

    def _get_client(self, region: Optional[str] = None) -> httpx.AsyncClient:
        if region and region in self._regional_clients:
            return self._regional_clients[region]
        if self._client is None:
            raise RuntimeError("MCPClient not initialized. Call initialize() first.")
        return self._client

    async def _check_breaker_or_raise(self, tool_name: str) -> bool:
        """Return True if circuit is OPEN (caller should fast-fail)."""
        if self._breaker and await self._breaker.is_open():
            logger.warning("mcp_circuit_open_fast_fail", tool=tool_name)
            TOOL_EXECUTIONS.labels(tool_name=tool_name, status="circuit_open").inc()
            return True
        return False

    async def execute_tool(
        self,
        tenant_id: str,
        tool_name: str,
        parameters: dict,
        session_id: str,
        trace_id: Optional[str] = None,
        crm_workspace_id: Optional[str] = None,
    ) -> dict:
        """Call the MCP Server's /execute endpoint to run a tool.

        Safety guarantees:
        - Hard timeout: ``TOOL_EXECUTION_TIMEOUT_SECONDS`` via asyncio.wait_for
        - Redis-backed circuit breaker: shared across all workers
        - Idempotency guard: non-idempotent tools (charge, book, etc.) raise
          immediately on timeout so callers do NOT retry them

        Returns the tool result as a dict.
        """
        if trace_id is None:
            trace_id = str(uuid.uuid4())

        if await self._check_breaker_or_raise(tool_name):
            return {"success": False, "error": "MCP service circuit breaker open", "tool_name": tool_name}

        payload = {
            "tenant_id": tenant_id,
            "tool_name": tool_name,
            "parameters": parameters,
            "session_id": session_id,
            "trace_id": trace_id,
            "crm_workspace_id": crm_workspace_id,
        }

        _t0 = time.monotonic()
        try:
            client = self._get_client()
            headers = {
                "X-Tenant-ID": tenant_id,
                "Authorization": f"Bearer {generate_internal_token(settings.SECRET_KEY, settings.JWT_ALGORITHM)}",
            }
            # Hard timeout — prevents indefinite worker blockage
            response = await asyncio.wait_for(
                client.post("/execute", json=payload, headers=headers),
                timeout=TOOL_EXECUTION_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            result = response.json()
            if self._breaker:
                await self._breaker.on_success()
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

        except asyncio.TimeoutError:
            if self._breaker:
                await self._breaker.on_failure()
            TOOL_EXECUTIONS.labels(tool_name=tool_name, status="timeout").inc()
            TOOL_LATENCY.labels(tool_name=tool_name).observe(time.monotonic() - _t0)
            # Non-idempotent tools must NOT be retried — the action may have partially executed.
            if not _is_idempotent(tool_name):
                logger.error(
                    "mcp_tool_timeout_non_idempotent",
                    tool=tool_name,
                    timeout_s=TOOL_EXECUTION_TIMEOUT_SECONDS,
                )
                return {
                    "success": False,
                    "error": f"Tool '{tool_name}' timed out. Action may have partially executed — do NOT retry.",
                    "tool_name": tool_name,
                    "idempotent": False,
                }
            logger.warning("mcp_tool_timeout_idempotent", tool=tool_name)
            raise httpx.TimeoutException(f"Tool {tool_name} timed out")

        except httpx.HTTPStatusError as exc:
            if exc.response.status_code >= 500 and self._breaker:
                await self._breaker.on_failure()
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
        except httpx.ConnectError as exc:
            # Connection errors are safe to surface for retry (no partial execution)
            if self._breaker:
                await self._breaker.on_failure()
            TOOL_EXECUTIONS.labels(tool_name=tool_name, status="error").inc()
            TOOL_LATENCY.labels(tool_name=tool_name).observe(time.monotonic() - _t0)
            logger.error("mcp_tool_connect_error", tool=tool_name, error=str(exc))
            # Only retry connect errors on idempotent tools
            if _is_idempotent(tool_name):
                raise  # let tenacity retry
            return {
                "success": False,
                "error": f"MCP server unreachable for tool '{tool_name}'",
                "tool_name": tool_name,
            }
        except Exception as exc:
            if self._breaker:
                await self._breaker.on_failure()
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
        region: Optional[str] = None,
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

        # Phase 6: Circuit Breaker for RAG
        if self._context_breaker and await self._context_breaker.is_open():
            logger.warning("mcp_context_breaker_open_skipping", tenant_id=tenant_id)
            CONTEXT_RETRIEVALS.labels(status="circuit_open").inc()
            return []

        _t0 = time.monotonic()
        try:
            client = self._get_client(region=region)
            response = await client.post(
                "/context/retrieve",
                json=payload,
                headers={
                    "X-Tenant-ID": tenant_id,
                    "Authorization": f"Bearer {generate_internal_token(settings.SECRET_KEY, settings.JWT_ALGORITHM)}",
                },
            )
            response.raise_for_status()
            data = response.json()
            items = data.get("items", data) if isinstance(data, dict) else data
            items = items if isinstance(items, list) else []
            
            if self._context_breaker:
                await self._context_breaker.on_success()
                
            status = "hit" if items else "miss"
            CONTEXT_RETRIEVALS.labels(status=status).inc()
            CONTEXT_ITEMS_RETURNED.observe(len(items))
            logger.info(
                "mcp_context_retrieved",
                tenant_id=tenant_id,
                region=region or "default",
                query_len=len(query),
                items_count=len(items),
            )
            return items
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code >= 500 and self._context_breaker:
                await self._context_breaker.on_failure()
            CONTEXT_RETRIEVALS.labels(status="error").inc()
            logger.warning("mcp_context_http_error", status=exc.response.status_code, region=region)
            return []
        except Exception as exc:
            if self._context_breaker:
                await self._context_breaker.on_failure()
            CONTEXT_RETRIEVALS.labels(status="error").inc()
            logger.warning("mcp_context_error", error=type(exc).__name__, region=region)
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
                headers={
                    "X-Tenant-ID": tenant_id,
                    "Authorization": f"Bearer {generate_internal_token(settings.SECRET_KEY, settings.JWT_ALGORITHM)}",
                },
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
                headers={
                    "X-Tenant-ID": tenant_id,
                    "Authorization": f"Bearer {generate_internal_token(settings.SECRET_KEY, settings.JWT_ALGORITHM)}",
                },
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

    # ── Knowledge Base Sync (for Agent Documents) ────────────────────────────────

    async def get_or_create_agent_kb(self, tenant_id: str, agent_id: str, agent_name: str, region: Optional[str] = None) -> str:
        """Retrieve the KB ID for an agent, creating it if it doesn't exist."""
        try:
            client = self._get_client(region=region)
            headers = {
                "X-Tenant-ID": tenant_id,
                "Authorization": f"Bearer {generate_internal_token(settings.SECRET_KEY, settings.JWT_ALGORITHM)}",
            }
            # 1. List existing KBs
            response = await client.get("/context/knowledge-bases", headers=headers)
            response.raise_for_status()
            kbs = response.json()
            
            for kb in kbs:
                if kb.get("agent_id") == agent_id:
                    return kb["id"]
            
            # 2. Not found, create it
            create_payload = {
                "name": f"Agent Knowledge: {agent_name}",
                "description": f"Internal knowledge for agent {agent_id}",
                "agent_id": agent_id
            }
            response = await client.post("/context/knowledge-bases", json=create_payload, headers=headers)
            response.raise_for_status()
            kb_data = response.json()
            return kb_data["id"]
            
        except Exception as exc:
            logger.error("mcp_kb_sync_failed", tenant_id=tenant_id, agent_id=agent_id, error=str(exc))
            raise

    async def upsert_knowledge_document(
        self, tenant_id: str, kb_id: str, title: str, content: str, doc_metadata: dict = None, region: Optional[str] = None
    ) -> str:
        """Push a document to the MCP Server knowledge base."""
        try:
            client = self._get_client(region=region)
            payload = {
                "title": title,
                "content": content,
                "content_type": "text",
                "doc_metadata": doc_metadata or {}
            }
            headers = {
                "X-Tenant-ID": tenant_id,
                "Authorization": f"Bearer {generate_internal_token(settings.SECRET_KEY, settings.JWT_ALGORITHM)}",
            }
            response = await client.post(
                f"/context/knowledge-bases/{kb_id}/documents",
                json=payload,
                headers=headers
            )
            response.raise_for_status()
            data = response.json()
            return data["id"]
        except Exception as exc:
            logger.error("mcp_doc_upsert_failed", tenant_id=tenant_id, kb_id=kb_id, error=str(exc))
            raise

    async def delete_knowledge_document(self, tenant_id: str, kb_id: str, doc_id: str, region: Optional[str] = None) -> bool:
        """Remove a document from the MCP Server knowledge base."""
        try:
            client = self._get_client(region=region)
            headers = {
                "X-Tenant-ID": tenant_id,
                "Authorization": f"Bearer {generate_internal_token(settings.SECRET_KEY, settings.JWT_ALGORITHM)}",
            }
            response = await client.delete(
                f"/context/knowledge-bases/{kb_id}/documents/{doc_id}",
                headers=headers
            )
            return response.status_code == 204
        except Exception as exc:
            logger.warning("mcp_doc_delete_failed", tenant_id=tenant_id, doc_id=doc_id, error=str(exc))
            return False

    async def cleanup_knowledge_by_metadata(
        self, tenant_id: str, kb_id: str, metadata_key: str, metadata_value: str, region: Optional[str] = None
    ) -> int:
        """Bulk delete chunks from MCP server matching metadata."""
        try:
            client = self._get_client(region=region)
            headers = {
                "X-Tenant-ID": tenant_id,
                "Authorization": f"Bearer {generate_internal_token(settings.SECRET_KEY, settings.JWT_ALGORITHM)}",
            }
            payload = {
                "metadata_key": metadata_key,
                "metadata_value": metadata_value
            }
            response = await client.post(
                f"/context/knowledge-bases/{kb_id}/documents/cleanup",
                json=payload,
                headers=headers
            )
            response.raise_for_status()
            return response.json().get("deleted_count", 0)
        except Exception as exc:
            logger.error("mcp_knowledge_cleanup_failed", tenant_id=tenant_id, kb_id=kb_id, error=str(exc))
            return 0

    async def wipe_tenant_knowledge(self, tenant_id: str) -> bool:
        """Call the high-performance bulk-wipe endpoint on the MCP server to erase all tenant RAG data."""
        try:
            client = self._get_client()
            headers = {
                "X-Tenant-ID": tenant_id,
                "Authorization": f"Bearer {generate_internal_token(settings.SECRET_KEY, settings.JWT_ALGORITHM)}",
            }
            response = await client.delete(
                f"/context/knowledge-bases/bulk-wipe",
                headers=headers
            )
            response.raise_for_status()
            logger.info("mcp_tenant_bulk_wipe_success", tenant_id=tenant_id)
            return True
        except Exception as exc:
            logger.error("mcp_tenant_bulk_wipe_failed", tenant_id=tenant_id, error=str(exc))
            return False
