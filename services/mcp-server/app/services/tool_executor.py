import asyncio
import time
import uuid
from typing import Any, Optional

import httpx
import jsonschema
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.tool import Tool, ToolExecution
from app.schemas.mcp import MCPToolCall, MCPToolResult
from app.services.tool_registry import ToolRegistry
from app.services.auth_manager import AuthManager

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Built-in handler imports (lazy to avoid circular imports)
# ---------------------------------------------------------------------------

async def _get_builtin_handlers() -> dict:
    from app.tools.builtin.pizza import handle_pizza_order, handle_order_status
    from app.tools.builtin.appointment import (
        handle_appointment_book,
        handle_appointment_list,
        handle_appointment_cancel,
    )
    from app.tools.builtin.crm import handle_crm_lookup, handle_crm_update
    from app.tools.builtin.sms import handle_send_sms

    return {
        "pizza_order": handle_pizza_order,
        "order_status": handle_order_status,
        "appointment_book": handle_appointment_book,
        "appointment_list": handle_appointment_list,
        "appointment_cancel": handle_appointment_cancel,
        "crm_lookup": handle_crm_lookup,
        "crm_update": handle_crm_update,
        "send_sms": handle_send_sms,
    }


class ValidationError(Exception):
    """Raised when tool input fails JSON Schema validation."""


class RateLimitError(Exception):
    """Raised when tool-level rate limit is exceeded."""


class ToolNotFoundError(Exception):
    """Raised when the requested tool does not exist."""


class ToolExecutor:
    """
    Orchestrates the full lifecycle of a tool call:
      1. Resolve tool from registry
      2. Validate input against JSON Schema
      3. Check per-tool rate limit (Redis)
      4. Execute (HTTP or built-in)
      5. Persist execution record
      6. Return structured MCPToolResult
    """

    def __init__(
        self,
        db: AsyncSession,
        redis,
        tenant_config: Optional[dict] = None,
    ) -> None:
        self.db = db
        self.redis = redis
        self.tenant_config: dict = tenant_config or {}
        self.registry = ToolRegistry(db)
        self.auth_manager = AuthManager()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute(
        self, tenant_id: str, tool_call: MCPToolCall
    ) -> MCPToolResult:
        """Execute a tool call end-to-end and return the result."""
        start_ms = int(time.time() * 1000)
        execution_id = str(uuid.uuid4())

        # 1. Resolve tool
        tool = await self.registry.get_tool(tenant_id, tool_call.tool_name)
        if not tool:
            return MCPToolResult(
                tool_name=tool_call.tool_name,
                error=f"Tool '{tool_call.tool_name}' not found or inactive",
                duration_ms=0,
                trace_id=tool_call.trace_id,
                status="failed",
            )

        # 2. Validate input
        try:
            await self._validate_input(tool.input_schema, tool_call.parameters)
        except ValidationError as exc:
            return MCPToolResult(
                tool_name=tool_call.tool_name,
                error=f"Input validation failed: {exc}",
                duration_ms=0,
                trace_id=tool_call.trace_id,
                status="failed",
            )

        # 3. Check per-tool rate limit
        try:
            await self._check_rate_limit(tenant_id, tool_call.tool_name, tool.rate_limit_per_minute)
        except RateLimitError:
            return MCPToolResult(
                tool_name=tool_call.tool_name,
                error=f"Tool rate limit exceeded ({tool.rate_limit_per_minute}/min)",
                duration_ms=0,
                trace_id=tool_call.trace_id,
                status="failed",
            )

        # 4. Create execution record
        execution = ToolExecution(
            id=uuid.UUID(execution_id),
            tenant_id=uuid.UUID(tenant_id),
            tool_id=tool.id,
            session_id=tool_call.session_id,
            trace_id=tool_call.trace_id,
            input_data=tool_call.parameters,
            status="running",
        )
        self.db.add(execution)
        await self.db.flush()

        # 5. Execute with timeout
        timeout = tool_call.timeout_override or tool.timeout_seconds
        result_data: Optional[dict] = None
        error_msg: Optional[str] = None
        status = "completed"

        try:
            result_data = await asyncio.wait_for(
                self._dispatch(tool, tool_call.parameters),
                timeout=float(timeout),
            )
        except asyncio.TimeoutError:
            error_msg = f"Tool execution timed out after {timeout}s"
            status = "timeout"
            logger.warning(
                "tool_execution_timeout",
                tool_name=tool_call.tool_name,
                tenant_id=tenant_id,
                timeout=timeout,
            )
        except Exception as exc:
            error_msg = str(exc)
            status = "failed"
            logger.error(
                "tool_execution_error",
                tool_name=tool_call.tool_name,
                tenant_id=tenant_id,
                error=str(exc),
                exc_info=exc,
            )

        # 6. Persist result
        end_ms = int(time.time() * 1000)
        duration_ms = end_ms - start_ms
        from datetime import datetime, timezone
        execution.status = status
        execution.output_data = result_data
        execution.error_message = error_msg
        execution.duration_ms = duration_ms
        execution.completed_at = datetime.now(timezone.utc)
        await self.db.flush()

        logger.info(
            "tool_executed",
            tool_name=tool_call.tool_name,
            tenant_id=tenant_id,
            status=status,
            duration_ms=duration_ms,
        )

        return MCPToolResult(
            tool_name=tool_call.tool_name,
            result=result_data,
            error=error_msg,
            duration_ms=duration_ms,
            trace_id=tool_call.trace_id,
            execution_id=execution_id,
            status=status,
        )

    # ------------------------------------------------------------------
    # Dispatching
    # ------------------------------------------------------------------

    async def _dispatch(self, tool: Tool, parameters: dict) -> dict:
        """Route to built-in or HTTP executor based on tool type."""
        if tool.is_builtin:
            return await self._execute_builtin_tool(tool, parameters)
        if tool.endpoint_url:
            return await self._execute_http_tool(tool, parameters)
        raise ValueError(
            f"Tool '{tool.name}' has no endpoint_url and is not a built-in tool"
        )

    async def _execute_http_tool(self, tool: Tool, parameters: dict) -> dict:
        """Execute an HTTP-based tool by posting parameters to its endpoint."""
        headers = await self.auth_manager.resolve_tool_auth(tool)
        headers.setdefault("Content-Type", "application/json")

        timeout = httpx.Timeout(float(tool.timeout_seconds))
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                tool.endpoint_url,
                json=parameters,
                headers=headers,
            )
            response.raise_for_status()
            return response.json()

    async def _execute_builtin_tool(self, tool: Tool, parameters: dict) -> dict:
        """Execute a platform built-in tool handler."""
        handlers = await _get_builtin_handlers()
        handler = handlers.get(tool.name)
        if not handler:
            raise ValueError(f"No built-in handler registered for tool '{tool.name}'")
        return await handler(parameters, self.tenant_config)

    # ------------------------------------------------------------------
    # Rate Limiting (per-tool, per-tenant)
    # ------------------------------------------------------------------

    async def _check_rate_limit(
        self, tenant_id: str, tool_name: str, limit_per_minute: int
    ) -> None:
        """
        Sliding window rate check for a specific tool.
        Raises RateLimitError if over limit.
        """
        if self.redis is None:
            return  # fail open if Redis unavailable

        now = time.time()
        window = 60  # 1 minute
        window_start = now - window
        key = f"tool_rate:{tenant_id}:{tool_name}"
        member = str(now)

        pipe = self.redis.pipeline()
        pipe.zremrangebyscore(key, "-inf", window_start)
        pipe.zadd(key, {member: now})
        pipe.zcard(key)
        pipe.expire(key, window)
        results = await pipe.execute()

        count: int = results[2]
        if count > limit_per_minute:
            raise RateLimitError(
                f"Tool '{tool_name}' rate limit {limit_per_minute}/min exceeded"
            )

    # ------------------------------------------------------------------
    # Input Validation
    # ------------------------------------------------------------------

    @staticmethod
    async def _validate_input(schema: dict, parameters: dict) -> None:
        """
        Validate parameters against a JSON Schema.
        Raises ValidationError with a descriptive message on failure.
        Empty/None schemas pass through without validation.
        """
        if not schema:
            return

        try:
            validator = jsonschema.Draft7Validator(schema)
            errors = sorted(validator.iter_errors(parameters), key=str)
            if errors:
                messages = [
                    f"{'.'.join(str(p) for p in e.absolute_path) or 'root'}: {e.message}"
                    for e in errors
                ]
                raise ValidationError("; ".join(messages))
        except jsonschema.SchemaError as exc:
            logger.warning("invalid_tool_schema", error=str(exc))
            # Don't block execution for a broken schema definition
