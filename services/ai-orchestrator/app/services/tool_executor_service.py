import asyncio
import re
import uuid
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from shared.orchestration.mcp_client import MCPClient
from shared.orchestration.llm_client import ToolCall
from app.models.agent import Session as AgentSession, PlaybookExecution
from app.models.variable import AgentVariable

logger = structlog.get_logger(__name__)

# Keys in Session.metadata_ that must never be overwritten by LLM tool calls.
_RESERVED_SESSION_KEYS = frozenset([
    "_escalation_state", "_voice_opening", "_greeting_only",
    "language", "_escalation_action",
])

_VAR_NAME_RE = re.compile(r'^[a-zA-Z][a-zA-Z0-9_]{0,63}$')
_MAX_VALUE_BYTES = 10000

_HIGH_RISK_TOOLS = frozenset([
    "stripe_create_payment_link", "stripe_check_payment",
    "twilio_send_sms",
    "gmail_send_email",
    "send_sms", "send_email", "create_payment_link",
])
_CONFIRMATION_PHRASES = frozenset([
    "yes", "confirm", "go ahead", "please do", "do it", "send it",
    "i confirm", "proceed", "ok", "okay", "correct", "that's right",
    "sure", "absolutely", "affirmative", "yep", "yeah",
])

class ToolExecutionService:
    def __init__(self, db: AsyncSession, mcp: MCPClient, redis_client):
        self.db = db
        self.mcp = mcp
        self.redis = redis_client

    @staticmethod
    def filter_unauthorized_tool_calls(tool_calls: list[ToolCall], enabled_tools: list[str]) -> list[ToolCall]:
        if not enabled_tools:
            return tool_calls
        allowed = set(enabled_tools)
        filtered = []
        for tc in tool_calls:
            if tc.name in allowed:
                filtered.append(tc)
            else:
                logger.warning(
                    "unauthorized_tool_call_blocked",
                    tool=tc.name,
                    enabled=list(allowed),
                )
        return filtered

    @staticmethod
    def requires_confirmation(tool_calls: list[ToolCall], user_message: str, history: list) -> str | None:
        high_risk = [tc for tc in tool_calls if tc.name in _HIGH_RISK_TOOLS]
        if not high_risk:
            return None

        msg_lower = user_message.lower().strip().rstrip(".,!")
        if any(phrase in msg_lower for phrase in _CONFIRMATION_PHRASES):
            return None

        tool_names = ", ".join(tc.name.replace("_", " ") for tc in high_risk)
        return (
            f"I'm about to {tool_names}. This action cannot be undone. "
            "Please reply 'confirm' to proceed or 'cancel' to abort."
        )

    @staticmethod
    def build_receipt_summary(tool_calls_made: list[dict]) -> str:
        receipts = []
        for entry in tool_calls_made:
            tool = entry.get("tool", "")
            if tool not in _HIGH_RISK_TOOLS:
                continue
            result = entry.get("result", {})
            if isinstance(result, dict) and result.get("error"):
                continue
            args = entry.get("arguments", {})
            if "stripe" in tool:
                amount = args.get("amount", "")
                currency = args.get("currency", "USD").upper()
                ref = (result or {}).get("payment_link_id", (result or {}).get("id", "N/A"))
                receipts.append(f"Payment of {amount} {currency} created. Reference: {ref}.")
            elif "sms" in tool or "twilio" in tool:
                to = args.get("to", args.get("phone_number", ""))
                receipts.append(f"SMS sent to {to}.")
            elif "email" in tool or "gmail" in tool:
                to = args.get("to", args.get("recipient", ""))
                receipts.append(f"Email sent to {to}.")
        return " ".join(receipts)

    async def execute_tool_calls(
        self,
        tool_calls: list[ToolCall],
        tenant_id: str,
        session_id: str,
        crm_workspace_id: str | None = None,
    ) -> list[dict]:
        """
        Execute all tool calls in parallel via the MCP client.
        Uses a distributed Redis lock to prevent race conditions during execution.
        """
        trace_id = str(uuid.uuid4())
        
        lock_manager = None
        if self.redis is not None:
            lock_manager = self.redis.lock(f"tool_lock:{tenant_id}:{session_id}", timeout=10)
        
        if lock_manager:
            try:
                await lock_manager.acquire(blocking=True, blocking_timeout=5)
            except Exception as e:
                logger.error("tool_execution_failed_to_acquire_lock", error=str(e), session_id=session_id)
                # Fail gracefully if lock cannot be acquired
                return [{"success": False, "error": "System is currently busy. Please try again.", "tool": tc.name} for tc in tool_calls]

        try:
            tasks = []
            for i, tc in enumerate(tool_calls):
                if tc.name == "set_session_variable":
                    tasks.append(self._handle_set_session_variable(session_id, tc.arguments))
                elif tc.name == "set_playbook_variable":
                    tasks.append(self._handle_set_playbook_variable(session_id, tc.arguments))
                else:
                    tasks.append(self.mcp.execute_tool(
                        tenant_id=tenant_id,
                        tool_name=tc.name,
                        parameters=tc.arguments,
                        session_id=session_id,
                        trace_id=f"{trace_id}-{i}",
                        crm_workspace_id=crm_workspace_id,
                    ))
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            processed: list[dict] = []
            for tc, result in zip(tool_calls, results):
                if isinstance(result, Exception):
                    logger.error(
                        "tool_execution_exception",
                        tool=tc.name,
                        error=str(result),
                    )
                    processed.append({"success": False, "error": str(result), "tool": tc.name})
                else:
                    processed.append(result)
            
            return processed
        finally:
            if lock_manager:
                try:
                    await lock_manager.release()
                except Exception:
                    pass

    async def _get_declared_variable_names(self, agent_id) -> set:
        """Return the set of declared AgentVariable names for this agent."""
        try:
            res = await self.db.execute(
                select(AgentVariable.name).where(AgentVariable.agent_id == agent_id)
            )
            return {row[0] for row in res.all()}
        except Exception:
            return set()  # Fail open — don't block execution on DB error here

    def _validate_runtime_var(self, name, value) -> str | None:
        """
        Validate a runtime variable name/value from an LLM tool call.
        Returns an error string if invalid, None if OK.
        """
        if not name or not _VAR_NAME_RE.match(str(name)):
            return "Invalid variable name — must start with a letter and contain only alphanumeric characters or underscores (max 64 chars)."
        if name in _RESERVED_SESSION_KEYS:
            return f"Cannot overwrite system-reserved key '{name}'."
        if len(str(value)) > _MAX_VALUE_BYTES:
            return f"Value too large (max {_MAX_VALUE_BYTES} bytes)."
        return None

    async def _handle_set_session_variable(self, session_id, arguments: dict) -> dict:
        name = arguments.get("name", "")
        value = arguments.get("value", "")

        err = self._validate_runtime_var(name, value)
        if err:
            logger.warning("set_session_variable_rejected", session_id=str(session_id), name=name, reason=err)
            return {"success": False, "error": err}

        res = await self.db.execute(select(AgentSession).where(AgentSession.id == session_id))
        session = res.scalar_one_or_none()
        if not session:
            return {"success": False, "error": "Session not found."}

        # FIX-09: Only allow writes to pre-declared variables and enforce type safety
        res = await self.db.execute(
            select(AgentVariable).where(AgentVariable.agent_id == session.agent_id)
        )
        declared_vars = {v.name: v for v in res.scalars().all()}
        
        if declared_vars and name not in declared_vars:
            logger.warning(
                "set_session_variable_undeclared",
                session_id=str(session_id),
                name=name,
                agent_id=str(session.agent_id),
            )
            return {"success": False, "error": f"Variable '{name}' is not declared for this agent."}

        # Type validation
        if name in declared_vars:
            v_def = declared_vars[name]
            expected_type = v_def.data_type
            
            # Simple type check
            type_ok = True
            if expected_type == "number":
                type_ok = isinstance(value, (int, float))
            elif expected_type == "boolean":
                type_ok = isinstance(value, bool)
            elif expected_type == "object":
                type_ok = isinstance(value, dict)
            elif expected_type == "string":
                type_ok = isinstance(value, str)
            
            if not type_ok:
                return {
                    "success": False, 
                    "error": f"Type mismatch for '{name}'. Expected {expected_type}, got {type(value).__name__}."
                }

        meta = dict(session.metadata_ or {})
        vars_ = dict(meta.get("variables", {}))
        vars_[name] = value
        meta["variables"] = vars_
        session.metadata_ = meta
        await self.db.commit()
        await self._invalidate_var_cache(session.agent_id)
        logger.info("set_session_variable", session_id=str(session_id), name=name)
        return {"success": True, "message": f"Global variable '{name}' set."}

    async def _handle_set_playbook_variable(self, session_id, arguments: dict) -> dict:
        name = arguments.get("name", "")
        value = arguments.get("value", "")

        err = self._validate_runtime_var(name, value)
        if err:
            logger.warning("set_playbook_variable_rejected", session_id=str(session_id), name=name, reason=err)
            return {"success": False, "error": err}

        res = await self.db.execute(
            select(PlaybookExecution).where(
                PlaybookExecution.session_id == session_id,
                PlaybookExecution.status == "active"
            ).order_by(PlaybookExecution.updated_at.desc())
        )
        pb_exec = res.scalars().first()
        if not pb_exec:
            return {"success": False, "error": "No active playbook execution found."}

        vars_ = dict(pb_exec.variables or {})
        vars_[name] = value
        pb_exec.variables = vars_
        await self.db.commit()
        
        # We need agent_id to invalidate cache; fetch from session backlink
        from app.models.agent import Session
        res = await self.db.execute(select(Session.agent_id).where(Session.id == session_id))
        agent_id = res.scalar()
        if agent_id:
            await self._invalidate_var_cache(agent_id)

        logger.info("set_playbook_variable", session_id=str(session_id), name=name)
        return {"success": True, "message": f"Playbook variable '{name}' set."}


    async def _invalidate_var_cache(self, agent_id: str):
        """Triggered after tool-based writes to clear stale context cache."""
        if not self.redis:
            return
        try:
            # Invalidate both global and any per-playbook cache entries
            async for key in self.redis.scan_iter(f"agent_variables:{agent_id}:*"):
                await self.redis.delete(key)
        except Exception:
            pass
