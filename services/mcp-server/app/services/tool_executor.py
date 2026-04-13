import asyncio
import json
import time
import uuid
from typing import Any, Optional

import httpx
import jsonschema
import structlog
import ipaddress
import urllib.parse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.crypto import decrypt_sensitive_fields
from app.models.tool import Tool, ToolExecution
from app.schemas.mcp import MCPToolCall, MCPToolResult
from app.services.tool_registry import ToolRegistry
from app.services.auth_manager import AuthManager
from app.services import pii_service

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
    from app.tools.integrations.google_calendar import (
        handle_google_calendar_check,
        handle_google_calendar_book,
    )
    from app.tools.integrations.calendly import (
        handle_calendly_availability,
        handle_calendly_book,
    )
    from app.tools.integrations.stripe_tool import (
        handle_stripe_payment_link,
        handle_stripe_check_payment,
    )
    from app.tools.integrations.twilio_sms import handle_twilio_send_sms
    from app.tools.integrations.gmail_smtp import handle_gmail_send_email
    from app.tools.integrations.google_sheets import (
        handle_google_sheets_read,
        handle_google_sheets_append,
    )
    from app.tools.integrations.webhook import handle_custom_webhook
    from app.tools.integrations.helcim_tool import handle_helcim_process_payment
    from app.tools.integrations.paypal_tool import handle_paypal_create_order
    from app.tools.integrations.moneris_tool import handle_moneris_process_payment
    from app.tools.integrations.square_tool import handle_square_create_payment
    from app.tools.integrations.mailchimp_tool import handle_mailchimp_add_subscriber
    from app.tools.integrations.telnyx_tool import handle_telnyx_send_bulk_sms
    from app.tools.builtin.twilio_pay import handle_twilio_pay
    from app.tools.builtin.agent_call import handle_agent_call

    return {
        # Demo / Built-in tools
        "pizza_order": handle_pizza_order,
        "order_status": handle_order_status,
        "appointment_book": handle_appointment_book,
        "appointment_list": handle_appointment_list,
        "appointment_cancel": handle_appointment_cancel,
        "crm_lookup": handle_crm_lookup,
        "crm_update": handle_crm_update,
        "send_sms": handle_send_sms,
        
        # Google Calendar
        "calendar_check_availability": handle_google_calendar_check,
        "calendar_book_appointment": handle_google_calendar_book,
        "google_calendar_check": handle_google_calendar_check,
        "google_calendar_book": handle_google_calendar_book,
        
        # Calendly
        "calendly_availability": handle_calendly_availability,
        "calendly_book": handle_calendly_book,
        "calendly_list_event_types": handle_calendly_availability,
        
        # Stripe
        "stripe_payment_link": handle_stripe_payment_link,
        "stripe_check_payment": handle_stripe_check_payment,
        "stripe_get_customer": handle_stripe_check_payment,
        
        # Twilio
        "twilio_send_sms": handle_twilio_send_sms,
        
        # Gmail / SMTP
        "gmail_send_email": handle_gmail_send_email,
        
        # Google Sheets
        "google_sheets_read": handle_google_sheets_read,
        "google_sheets_append": handle_google_sheets_append,
        
        # Webhook
        "custom_webhook": handle_custom_webhook,
        
        # Integrations
        "moneris_process_payment": handle_moneris_process_payment,
        "square_create_payment": handle_square_create_payment,
        "helcim_process_payment": handle_helcim_process_payment,
        "paypal_create_order": handle_paypal_create_order,
        "mailchimp_add_subscriber": handle_mailchimp_add_subscriber,
        "telnyx_send_bulk_sms": handle_telnyx_send_bulk_sms,
        "twilio_pay_initiate": handle_twilio_pay,
        # Agent-as-Tool
        "agent_call": handle_agent_call,
    }


class ValidationError(Exception):
    """Raised when tool input fails JSON Schema validation."""


class RateLimitError(Exception):
    """Raised when tool-level rate limit is exceeded."""


class ToolNotFoundError(Exception):
    """Raised when the requested tool does not exist."""


class SSRFError(Exception):
    """Raised when a tool URL targets a private or internal address."""


_PRIVATE_PREFIXES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def _validate_tool_url(url: str) -> None:
    """
    Reject URLs that target localhost, private/internal IPs, or use non-HTTPS
    schemes. Prevents SSRF via tool execution.
    """
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        raise SSRFError("Invalid tool URL.")

    if parsed.scheme != "https":
        raise SSRFError("Tool URL must use HTTPS.")

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise SSRFError("Tool URL must include a hostname.")

    # Block common internal hostnames
    if hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0", "postgres", "redis", "db", "api-gateway", "ai-orchestrator"):
        raise SSRFError(f"Tool URL must not target internal service: {hostname}")

    # Resolve and validate IPs — includes literal IPs and DNS-resolved domain names.
    # Resolving the hostname here closes the DNS rebinding window: an attacker cannot
    # pass validation with a public IP and then swap DNS to a private one mid-flight
    # (the resolved IP is what we actually validate, not the name).
    import socket
    try:
        resolved = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
        for _family, _type, _proto, _canonname, sockaddr in resolved:
            ip_str = sockaddr[0]
            try:
                ip = ipaddress.ip_address(ip_str)
                for net in _PRIVATE_PREFIXES:
                    if ip in net:
                        raise SSRFError(
                            f"Tool URL resolves to a private or reserved IP address: {ip_str}"
                        )
            except ValueError:
                pass  # malformed addr — skip
    except SSRFError:
        raise
    except OSError as exc:
        raise SSRFError(f"Tool URL hostname could not be resolved: {exc}") from exc


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

        # 4. Create execution record. Redact input_data before DB persistence.
        redacted_input = pii_service.redact_dict(tool_call.parameters, pii_service.PIIContext())
        execution = ToolExecution(
            id=uuid.UUID(execution_id),
            tenant_id=uuid.UUID(tenant_id),
            tool_id=tool.id,
            session_id=tool_call.session_id,
            trace_id=tool_call.trace_id,
            input_data=redacted_input,
            status="running",
        )
        self.db.add(execution)
        await self.db.flush()

        # 5. Execute with timeout
        # Cap timeout_override to prevent resource exhaustion attacks (High fix)
        _MAX_TIMEOUT = getattr(settings, "MAX_TOOL_TIMEOUT_SECONDS", 300)
        raw_timeout = tool_call.timeout_override or tool.timeout_seconds
        timeout = min(float(raw_timeout), float(_MAX_TIMEOUT))
        result_data: Optional[dict] = None
        error_msg: Optional[str] = None
        status = "completed"

        try:
            result_data = await asyncio.wait_for(
                self._dispatch(
                    tool,
                    tool_call.parameters,
                    session_id=tool_call.session_id,
                    tenant_id=tenant_id,
                ),
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

        # 6. Persist result (Redact output_data)
        end_ms = int(time.time() * 1000)
        duration_ms = end_ms - start_ms
        from datetime import datetime, timezone
        execution.status = status
        
        redacted_output = None
        if result_data:
            redacted_output = pii_service.redact_dict(result_data, pii_service.PIIContext())
            
        execution.output_data = redacted_output
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

    async def test_execute(
        self, tenant_id: str, tool: Tool, tool_call: MCPToolCall
    ) -> MCPToolResult:
        """
        Execute a tool call for testing (e.g. from the Admin/Config UI)
        without persisting to the execution history DB and using a transient Tool object.
        """
        start_ms = int(time.time() * 1000)

        # 1. Validate input against the transient tool's schema
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

        # 2. Add an ad-hoc rate limit for test_execute to prevent abuse of the test endpoint
        try:
            await self._check_rate_limit(tenant_id, f"test_{tool.name}", 10) # Max 10 tests / min
        except RateLimitError:
             return MCPToolResult(
                tool_name=tool_call.tool_name,
                error=f"Too many test executions. Please wait and try again.",
                duration_ms=0,
                trace_id=tool_call.trace_id,
                status="failed",
            )

        # 3. Execute with timeout
        # Cap timeout_override to prevent resource exhaustion attacks
        _MAX_TIMEOUT = getattr(settings, "MAX_TOOL_TIMEOUT_SECONDS", 300)
        raw_timeout = tool_call.timeout_override or tool.timeout_seconds
        timeout = min(float(raw_timeout), float(_MAX_TIMEOUT))
        result_data: Optional[dict] = None
        error_msg: Optional[str] = None
        status = "completed"

        try:
            result_data = await asyncio.wait_for(
                self._dispatch(
                    tool,
                    tool_call.parameters,
                    session_id=tool_call.session_id,
                    tenant_id=tenant_id,
                ),
                timeout=float(timeout),
            )
        except asyncio.TimeoutError:
            error_msg = f"Tool execution timed out after {timeout}s"
            status = "timeout"
        except Exception as exc:
            error_msg = str(exc)
            status = "failed"
            logger.error(
                "tool_test_execution_error",
                tool_name=tool.name,
                tenant_id=tenant_id,
                error=str(exc),
            )

        end_ms = int(time.time() * 1000)
        duration_ms = end_ms - start_ms

        logger.info(
            "tool_test_executed",
            tool_name=tool.name,
            tenant_id=tenant_id,
            status=status,
            duration_ms=duration_ms,
        )

        return MCPToolResult(
            tool_name=tool.name,
            result=result_data,
            error=error_msg,
            duration_ms=duration_ms,
            trace_id=tool_call.trace_id,
            execution_id=None,
            status=status,
        )

    # ------------------------------------------------------------------
    # Dispatching
    # ------------------------------------------------------------------

    async def _dispatch(
        self,
        tool: Tool,
        parameters: dict,
        session_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> dict:
        """Route to built-in or HTTP executor based on tool type."""
        if tool.is_builtin:
            return await self._execute_builtin_tool(
                tool, parameters, session_id=session_id, tenant_id=tenant_id
            )
        if tool.endpoint_url:
            return await self._execute_http_tool(tool, parameters)
        raise ValueError(
            f"Tool '{tool.name}' has no endpoint_url and is not a built-in tool"
        )

    async def _execute_http_tool(self, tool: Tool, parameters: dict) -> dict:
        """Execute an HTTP-based tool by posting parameters to its endpoint."""
        # ── 0. SSRF Guard ──────────────────────────────────────────────────
        try:
            _validate_tool_url(tool.endpoint_url)
        except SSRFError as exc:
            logger.warning("tool_ssrf_blocked", tool_name=tool.name, url=tool.endpoint_url)
            raise ValueError(f"SSRF Protection: {str(exc)}")

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

    async def _execute_builtin_tool(
        self,
        tool: Tool,
        parameters: dict,
        session_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> dict:
        """Execute a platform built-in tool handler.

        Dispatch order:
          1. wf:* tool names → WorkflowExecutor (general-purpose workflow engine).
          2. Try the new MCP adapter registry (provider-isolated, SDK-backed).
          3. Fall back to the legacy handler dict for tools not yet migrated.

        Integration tools (calendar, Stripe, etc.) read their credentials from
        tool.tool_metadata, which is set per-tenant via the tools UI.
        """
        # ── Workflow engine dispatch (wf:* tools) ──────────────────────
        if tool.name.startswith("wf:"):
            from app.services.workflow_executor import execute_workflow_tool
            return await execute_workflow_tool(
                tool_name=tool.name,
                parameters=parameters,
                tool_metadata=tool.tool_metadata or {},
                session_id=session_id or "",
                tenant_id=tenant_id or str(tool.tenant_id),
                agent_id=(tool.tool_metadata or {}).get("agent_id"),
            )

        from app.integrations.base import ACTION_REGISTRY
        from app.integrations.errors import IntegrationException

        # Decrypt credentials stored in tool_metadata before passing to handler
        decrypted_metadata = decrypt_sensitive_fields(tool.tool_metadata or {})
        config = {**self.tenant_config, **decrypted_metadata}

        # ── Try new adapter registry first ─────────────────────────────
        canonical_action = ACTION_REGISTRY.resolve_action(tool.name)
        if canonical_action:
            provider = ACTION_REGISTRY.provider_for_tool_name(tool.name)
            adapter = ACTION_REGISTRY.get_adapter(provider) if provider else None
            if adapter and canonical_action in adapter.supported_actions:
                try:
                    return await adapter.execute(canonical_action, parameters, config)
                except IntegrationException as exc:
                    # Surface normalized error to the tool result
                    raise ValueError(str(exc.error))

        # ── Legacy handler fallback ────────────────────────────────────
        handlers = await _get_builtin_handlers()
        handler = handlers.get(tool.name)
        if not handler:
            raise ValueError(f"No built-in handler registered for tool '{tool.name}'")
        return await handler(parameters, config)

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
            # Fail-closed for high-risk tools when Redis is unavailable.
            # For non-critical tools we fail-open to maintain availability.
            _HIGH_RISK = {"stripe_payment_link", "stripe_check_payment",
                          "twilio_send_sms", "gmail_send_email", "send_sms", "send_email"}
            if tool_name in _HIGH_RISK:
                raise RateLimitError(
                    f"Rate-limit service unavailable — '{tool_name}' requires Redis to be online."
                )
            return  # fail open for low-risk tools

        now = time.time()
        window = 60  # 1 minute
        window_start = now - window
        key = f"tenant:{tenant_id}:tool_rate:{tool_name}"
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
        # Size guard: reject oversized parameter payloads
        _MAX_PARAM_BYTES = getattr(settings, "MAX_TOOL_PARAM_BYTES", 32_768)
        param_size = len(json.dumps(parameters).encode("utf-8")) if parameters else 0
        if param_size > _MAX_PARAM_BYTES:
            raise ValidationError(
                f"Parameter payload too large: {param_size} bytes (max {_MAX_PARAM_BYTES})"
            )

        # Depth guard: reject deeply nested structures
        def _check_depth(obj, max_depth=5, current=0):
            if current > max_depth:
                raise ValidationError(f"Parameter nesting exceeds max depth of {max_depth}")
            if isinstance(obj, dict):
                for v in obj.values():
                    _check_depth(v, max_depth, current + 1)
            elif isinstance(obj, list):
                for item in obj:
                    _check_depth(item, max_depth, current + 1)

        _check_depth(parameters)

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
