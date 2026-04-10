import asyncio
import uuid
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.services.mcp_client import MCPClient
from app.services.llm_client import ToolCall
from app.models.agent import Session as AgentSession, PlaybookExecution

logger = structlog.get_logger(__name__)

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

    async def _handle_set_session_variable(self, session_id, arguments: dict) -> dict:
        res = await self.db.execute(select(AgentSession).where(AgentSession.id == session_id))
        session = res.scalar_one_or_none()
        if session:
            meta = dict(session.metadata_ or {})
            vars = meta.get("variables", {})
            vars[arguments.get("name")] = arguments.get("value")
            meta["variables"] = vars
            session.metadata_ = meta
            return {"success": True, "message": f"Global variable '{arguments.get('name')}' set."}
        return {"success": False, "error": "Session not found."}

    async def _handle_set_playbook_variable(self, session_id, arguments: dict) -> dict:
        res = await self.db.execute(
            select(PlaybookExecution).where(
                PlaybookExecution.session_id == session_id,
                PlaybookExecution.status == "active"
            ).order_by(PlaybookExecution.updated_at.desc())
        )
        pb_exec = res.scalars().first()
        if pb_exec:
            vars = dict(pb_exec.variables or {})
            vars[arguments.get("name")] = arguments.get("value")
            pb_exec.variables = vars
            return {"success": True, "message": f"Playbook variable '{arguments.get('name')}' set."}
        return {"success": False, "error": "No active playbook execution found."}
