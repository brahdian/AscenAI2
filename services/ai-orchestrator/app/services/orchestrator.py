import asyncio
import time
import uuid
from datetime import datetime, date, timezone
from typing import AsyncGenerator, Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func

import json

from app.core.config import settings
from app.models.agent import Agent, AgentPlaybook, AgentGuardrails, Session as AgentSession, Message, AgentAnalytics
from app.schemas.chat import ChatResponse, StreamChatEvent
from app.services.llm_client import LLMClient, LLMResponse, ToolCall
from app.services.mcp_client import MCPClient
from app.services.memory_manager import MemoryManager
from app.services.intent_detector import IntentDetector
from app.prompts.system_prompts import build_system_prompt

logger = structlog.get_logger(__name__)

MAX_TOOL_ITERATIONS = settings.MAX_TOOL_ITERATIONS
ESCALATION_KEYWORDS = [
    "speak to human", "talk to agent", "real person", "supervisor",
    "I can't help", "beyond my capabilities", "escalating",
]
# Module-level constant — do NOT define inside the hot-path _check_input_guardrails
_PROFANITY_LIST = frozenset([
    "fuck", "shit", "bitch", "asshole", "cunt", "bastard",
])


class Orchestrator:
    """
    Core orchestration engine for the AI assistant.

    Manages the full request lifecycle:
    - Memory retrieval
    - Context augmentation via MCP
    - LLM reasoning with tool use
    - Tool execution via MCP
    - Response generation and persistence
    - Analytics tracking
    """

    def __init__(
        self,
        llm_client: LLMClient,
        mcp_client: MCPClient,
        memory_manager: MemoryManager,
        db: AsyncSession,
        redis_client=None,
    ):
        self.llm = llm_client
        self.mcp = mcp_client
        self.memory = memory_manager
        self.db = db
        self.redis = redis_client
        self.intent_detector = IntentDetector()

    # ------------------------------------------------------------------
    # Helpers: playbook + corrections
    # ------------------------------------------------------------------

    async def _load_playbook(self, agent_id) -> Optional[AgentPlaybook]:
        """Load the active playbook for this agent, if any."""
        from sqlalchemy import select as sa_select
        result = await self.db.execute(
            sa_select(AgentPlaybook).where(
                AgentPlaybook.agent_id == agent_id,
                AgentPlaybook.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def _load_corrections(self, agent_id: str) -> list[dict]:
        """Fetch operator corrections stored in Redis for this agent."""
        if self.redis is None:
            return []
        try:
            key = f"corrections:{agent_id}"
            raw_items = await self.redis.lrange(key, 0, 19)
            corrections = []
            for raw in raw_items:
                try:
                    corrections.append(json.loads(raw))
                except Exception:
                    pass
            return corrections
        except Exception:
            return []

    async def _load_guardrails(self, agent_id):
        """Load active guardrails for this agent."""
        from app.models.agent import AgentGuardrails
        from sqlalchemy import select as sa_select
        result = await self.db.execute(
            sa_select(AgentGuardrails).where(
                AgentGuardrails.agent_id == agent_id,
                AgentGuardrails.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    def _check_input_guardrails(self, user_message: str, guardrails) -> Optional[str]:
        """Return a block reason string if message should be blocked, else None."""
        if not guardrails:
            return None
        msg_lower = user_message.lower()

        # Hard keyword block
        for kw in (guardrails.blocked_keywords or []):
            if kw.lower() in msg_lower:
                return f"blocked_keyword:{kw}"

        # Profanity filter
        if guardrails.profanity_filter:
            for word in _PROFANITY_LIST:
                if word in msg_lower:
                    return "profanity"

        return None

    def _apply_output_guardrails(self, response: str, guardrails) -> str:
        """Apply output-side guardrails: PII redaction, length cap, disclaimer."""
        import re
        if not guardrails:
            return response

        if guardrails.pii_redaction:
            response = re.sub(r'\b[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}\b', '[EMAIL]', response)
            response = re.sub(r'\b(\+?[\d][\d\s\-().]{7,}\d)\b', '[PHONE]', response)
            response = re.sub(r'\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b', '[CARD]', response)

        if guardrails.max_response_length and len(response) > guardrails.max_response_length:
            response = response[:guardrails.max_response_length].rstrip() + "…"

        if guardrails.require_disclaimer:
            response = response + "\n\n" + guardrails.require_disclaimer

        return response

    def _is_fallback_response(self, response: str, playbook) -> bool:
        """Detect if the response is a fallback/uncertain reply."""
        fallback_phrases = [
            "i don't know", "i'm not sure", "i cannot help",
            "i'm unable to", "beyond my", "i don't have information",
        ]
        r = response.lower()
        if any(phrase in r for phrase in fallback_phrases):
            return True
        if playbook and playbook.fallback_response:
            if playbook.fallback_response.strip().lower() in r:
                return True
        return False

    async def _maybe_send_greeting(
        self, agent: Agent, session: AgentSession, playbook: Optional[AgentPlaybook]
    ) -> Optional[str]:
        """
        If this is a brand-new session (no messages yet) and the playbook
        has a greeting, persist it and return the greeting text.
        """
        if not playbook or not playbook.greeting_message:
            return None

        from sqlalchemy import select as sa_select, func as sa_func
        count_result = await self.db.execute(
            sa_select(sa_func.count()).select_from(Message).where(
                Message.session_id == session.id
            )
        )
        msg_count = count_result.scalar() or 0
        if msg_count > 0:
            return None  # Not a new session

        greeting = playbook.greeting_message
        self.db.add(Message(
            session_id=session.id,
            tenant_id=session.tenant_id,
            role="assistant",
            content=greeting,
            tokens_used=0,
            latency_ms=0,
        ))
        await self.memory.add_to_short_term_memory(
            session.id, {"role": "assistant", "content": greeting}
        )
        return greeting

    async def process_message(
        self,
        agent: Agent,
        session: AgentSession,
        user_message: str,
        stream: bool = False,
    ) -> ChatResponse | AsyncGenerator:
        """
        Main orchestration loop for processing a user message.

        Steps:
        1. Load conversation memory (last N messages from Redis)
        2. Retrieve context from MCP (knowledge base, customer history)
        3. Build system prompt with injected context
        4. Get available tool schemas for this agent
        5. Call LLM with messages + tools
        6. If LLM returns tool_calls, execute each via MCP and re-call LLM
        7. Repeat tool loop up to MAX_TOOL_ITERATIONS
        8. Save messages to memory and DB
        9. Update analytics
        10. Return ChatResponse
        """
        if stream:
            return self.stream_response(agent, session, user_message)

        start_time = time.monotonic()
        tenant_id = str(session.tenant_id)
        session_id = session.id

        # --- Pre-classification ---
        intent = self.intent_detector.detect_intent(user_message)
        if self.intent_detector.should_escalate_immediately(user_message):
            return await self._build_escalation_response(
                agent, session, user_message, start_time
            )

        # --- Load playbook + corrections ---
        playbook = await self._load_playbook(agent.id)
        corrections = await self._load_corrections(str(agent.id))
        await self._maybe_send_greeting(agent, session, playbook)

        guardrails = await self._load_guardrails(agent.id)

        # --- Input guardrail check ---
        block_reason = self._check_input_guardrails(user_message, guardrails)
        if block_reason:
            block_msg = (guardrails.blocked_message if guardrails else "I'm sorry, I can't help with that.")
            # Persist the blocked user message for learning insights
            blocked_user_msg = Message(
                session_id=session_id,
                tenant_id=session.tenant_id,
                role="user",
                content=user_message,
                guardrail_triggered=block_reason,
                tokens_used=0,
                latency_ms=0,
            )
            self.db.add(blocked_user_msg)
            latency_ms = int((time.monotonic() - start_time) * 1000)
            return ChatResponse(
                session_id=session_id,
                message=block_msg,
                tool_calls_made=[],
                suggested_actions=[],
                escalate_to_human=False,
                latency_ms=latency_ms,
                tokens_used=0,
            )

        # --- Step 1: Load short-term memory ---
        history = await self.memory.get_short_term_memory(session_id)
        summary = await self.memory.get_session_summary(session_id)

        # --- Step 2: Retrieve MCP context ---
        kb_ids = agent.knowledge_base_ids or []
        context_items = await self.mcp.retrieve_context(
            tenant_id=tenant_id,
            query=user_message,
            session_id=session_id,
            context_types=["knowledge", "history"],
            knowledge_base_ids=kb_ids if kb_ids else None,
        )

        # --- Step 3: Build system prompt ---
        customer_profile: dict = {}
        if session.customer_identifier:
            customer_profile = await self.memory.get_long_term_customer_memory(
                tenant_id, session.customer_identifier
            )

        system_prompt = build_system_prompt(
            agent=agent,
            context_items=context_items,
            business_info={"customer_profile": customer_profile, "intent": intent},
            playbook=playbook,
            corrections=corrections,
            guardrails=guardrails,
        )

        # --- Step 4: Get tool schemas ---
        tool_schemas = await self._get_agent_tools_schema(agent, tenant_id)

        # --- Build message list for LLM ---
        messages = [{"role": "system", "content": system_prompt}]

        if summary:
            messages.append({
                "role": "system",
                "content": f"[Conversation summary so far]: {summary}",
            })

        messages.extend(history)
        messages.append({"role": "user", "content": user_message})

        # --- Step 5-7: Tool-augmented LLM loop ---
        tool_calls_made: list[dict] = []
        total_tokens = 0
        llm_config = agent.llm_config or {}
        temperature = llm_config.get("temperature", 0.7)
        max_tokens = llm_config.get("max_tokens", settings.MAX_RESPONSE_TOKENS)

        final_response: Optional[str] = None
        iterations = 0

        while iterations < MAX_TOOL_ITERATIONS:
            llm_response: LLMResponse = await self.llm.complete(
                messages=messages,
                tools=tool_schemas if tool_schemas else None,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=False,
            )

            total_tokens += llm_response.usage.total_tokens

            if llm_response.tool_calls:
                iterations += 1
                # Execute all tool calls in parallel
                tool_results = await self._execute_tool_calls(
                    tool_calls=llm_response.tool_calls,
                    tenant_id=tenant_id,
                    session_id=session_id,
                )

                # Record tool calls for response metadata
                for tc, result in zip(llm_response.tool_calls, tool_results):
                    tool_calls_made.append({
                        "tool": tc.name,
                        "arguments": tc.arguments,
                        "result": result,
                    })

                # Append assistant message with tool calls
                messages.append({
                    "role": "assistant",
                    "content": llm_response.content or "",
                    "tool_calls": [
                        {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                        for tc in llm_response.tool_calls
                    ],
                })

                # Append tool results
                for tc, result in zip(llm_response.tool_calls, tool_results):
                    messages.append({
                        "role": "tool",
                        "name": tc.name,
                        "tool_call_id": tc.id,
                        "content": str(result),
                    })
            else:
                # No more tool calls - we have the final answer
                final_response = llm_response.content or ""
                break

        if final_response is None:
            # Max iterations reached; use last response content
            final_response = llm_response.content or "I'm sorry, I was unable to complete your request."

        latency_ms = int((time.monotonic() - start_time) * 1000)

        final_response = self._apply_output_guardrails(final_response, guardrails)
        is_fallback = self._is_fallback_response(final_response, playbook)

        # --- Step 8: Persist to memory ---
        await self.memory.add_to_short_term_memory(session_id, {"role": "user", "content": user_message})
        await self.memory.add_to_short_term_memory(session_id, {"role": "assistant", "content": final_response})

        # --- Persist messages to DB ---
        user_msg = Message(
            session_id=session_id,
            tenant_id=session.tenant_id,
            role="user",
            content=user_message,
            tokens_used=0,
            latency_ms=0,
        )
        assistant_msg = Message(
            session_id=session_id,
            tenant_id=session.tenant_id,
            role="assistant",
            content=final_response,
            tool_calls=tool_calls_made if tool_calls_made else None,
            tokens_used=total_tokens,
            latency_ms=latency_ms,
            is_fallback=is_fallback,
        )
        self.db.add(user_msg)
        self.db.add(assistant_msg)

        # --- Step 9: Update analytics ---
        await self._update_analytics(
            tenant_id=session.tenant_id,
            agent_id=session.agent_id,
            tokens=total_tokens,
            latency_ms=latency_ms,
            tool_count=len(tool_calls_made),
        )

        # --- Step 10: Escalation check ---
        should_escalate = await self._should_escalate(agent, final_response, messages)
        if should_escalate:
            session.status = "escalated"

        suggested_actions = self._extract_suggested_actions(final_response, intent)

        return ChatResponse(
            session_id=session_id,
            message=final_response,
            tool_calls_made=tool_calls_made,
            suggested_actions=suggested_actions,
            escalate_to_human=should_escalate,
            latency_ms=latency_ms,
            tokens_used=total_tokens,
        )

    async def stream_response(
        self,
        agent: Agent,
        session: AgentSession,
        user_message: str,
    ) -> AsyncGenerator[StreamChatEvent, None]:
        """
        Streaming version of process_message.
        Yields StreamChatEvent objects for real-time delivery via SSE or WebSocket.
        """
        tenant_id = str(session.tenant_id)
        session_id = session.id
        start_time = time.monotonic()

        intent = self.intent_detector.detect_intent(user_message)

        if self.intent_detector.should_escalate_immediately(user_message):
            yield StreamChatEvent(
                type="text_delta",
                data="I'll connect you with a human agent right away. Please hold on.",
                session_id=session_id,
            )
            yield StreamChatEvent(
                type="done",
                data={"escalate": True, "session_id": session_id},
                session_id=session_id,
            )
            return

        # Load memory and context
        playbook = await self._load_playbook(agent.id)
        corrections = await self._load_corrections(str(agent.id))
        await self._maybe_send_greeting(agent, session, playbook)

        guardrails = await self._load_guardrails(agent.id)

        # --- Input guardrail check ---
        block_reason = self._check_input_guardrails(user_message, guardrails)
        if block_reason:
            block_msg = (guardrails.blocked_message if guardrails else "I'm sorry, I can't help with that.")
            blocked_user_msg = Message(
                session_id=session_id,
                tenant_id=session.tenant_id,
                role="user",
                content=user_message,
                guardrail_triggered=block_reason,
                tokens_used=0,
                latency_ms=0,
            )
            self.db.add(blocked_user_msg)
            yield StreamChatEvent(
                type="text_delta",
                data=block_msg,
                session_id=session_id,
            )
            yield StreamChatEvent(
                type="done",
                data={"session_id": session_id, "latency_ms": 0, "tokens_used": 0,
                      "tool_calls_made": 0, "escalate_to_human": False},
                session_id=session_id,
            )
            return

        history = await self.memory.get_short_term_memory(session_id)
        summary = await self.memory.get_session_summary(session_id)
        kb_ids = agent.knowledge_base_ids or []

        context_items = await self.mcp.retrieve_context(
            tenant_id=tenant_id,
            query=user_message,
            session_id=session_id,
            context_types=["knowledge", "history"],
            knowledge_base_ids=kb_ids if kb_ids else None,
        )

        customer_profile: dict = {}
        if session.customer_identifier:
            customer_profile = await self.memory.get_long_term_customer_memory(
                tenant_id, session.customer_identifier
            )

        system_prompt = build_system_prompt(
            agent=agent,
            context_items=context_items,
            business_info={"customer_profile": customer_profile, "intent": intent},
            playbook=playbook,
            corrections=corrections,
            guardrails=guardrails,
        )

        tool_schemas = await self._get_agent_tools_schema(agent, tenant_id)

        messages = [{"role": "system", "content": system_prompt}]
        if summary:
            messages.append({"role": "system", "content": f"[Summary]: {summary}"})
        messages.extend(history)
        messages.append({"role": "user", "content": user_message})

        llm_config = agent.llm_config or {}
        temperature = llm_config.get("temperature", 0.7)
        max_tokens = llm_config.get("max_tokens", settings.MAX_RESPONSE_TOKENS)

        tool_calls_made: list[dict] = []
        total_tokens = 0
        full_response_text = ""

        # If there are tools, do non-streaming tool loop first, then stream the final answer
        if tool_schemas:
            iterations = 0
            llm_response = None
            while iterations < MAX_TOOL_ITERATIONS:
                llm_response = await self.llm.complete(
                    messages=messages,
                    tools=tool_schemas,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=False,
                )
                total_tokens += llm_response.usage.total_tokens

                if llm_response.tool_calls:
                    iterations += 1
                    yield StreamChatEvent(
                        type="tool_call",
                        data={
                            "tools": [
                                {"name": tc.name, "arguments": tc.arguments}
                                for tc in llm_response.tool_calls
                            ]
                        },
                        session_id=session_id,
                    )

                    tool_results = await self._execute_tool_calls(
                        tool_calls=llm_response.tool_calls,
                        tenant_id=tenant_id,
                        session_id=session_id,
                    )

                    for tc, result in zip(llm_response.tool_calls, tool_results):
                        tool_calls_made.append({
                            "tool": tc.name,
                            "arguments": tc.arguments,
                            "result": result,
                        })
                        yield StreamChatEvent(
                            type="tool_result",
                            data={"tool": tc.name, "result": result},
                            session_id=session_id,
                        )

                    messages.append({
                        "role": "assistant",
                        "content": llm_response.content or "",
                        "tool_calls": [
                            {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                            for tc in llm_response.tool_calls
                        ],
                    })
                    for tc, result in zip(llm_response.tool_calls, tool_results):
                        messages.append({
                            "role": "tool",
                            "name": tc.name,
                            "tool_call_id": tc.id,
                            "content": str(result),
                        })
                else:
                    full_response_text = llm_response.content or ""
                    break

            if not full_response_text and llm_response:
                full_response_text = llm_response.content or "I was unable to complete your request."

            # Stream the final text word by word for a natural feel
            words = full_response_text.split(" ")
            for word in words:
                yield StreamChatEvent(
                    type="text_delta",
                    data=word + " ",
                    session_id=session_id,
                )
                await asyncio.sleep(0.01)
        else:
            # No tools — use real streaming
            gen = await self.llm.complete(
                messages=messages,
                tools=None,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )
            async for chunk in gen:
                full_response_text += chunk
                yield StreamChatEvent(
                    type="text_delta",
                    data=chunk,
                    session_id=session_id,
                )

        latency_ms = int((time.monotonic() - start_time) * 1000)

        full_response_text = self._apply_output_guardrails(full_response_text, guardrails)
        is_fallback = self._is_fallback_response(full_response_text, playbook)

        # Persist to memory and DB
        await self.memory.add_to_short_term_memory(session_id, {"role": "user", "content": user_message})
        await self.memory.add_to_short_term_memory(session_id, {"role": "assistant", "content": full_response_text})

        user_msg = Message(
            session_id=session_id,
            tenant_id=session.tenant_id,
            role="user",
            content=user_message,
            tokens_used=0,
            latency_ms=0,
        )
        assistant_msg = Message(
            session_id=session_id,
            tenant_id=session.tenant_id,
            role="assistant",
            content=full_response_text,
            tool_calls=tool_calls_made if tool_calls_made else None,
            tokens_used=total_tokens,
            latency_ms=latency_ms,
            is_fallback=is_fallback,
        )
        self.db.add(user_msg)
        self.db.add(assistant_msg)

        await self._update_analytics(
            tenant_id=session.tenant_id,
            agent_id=session.agent_id,
            tokens=total_tokens,
            latency_ms=latency_ms,
            tool_count=len(tool_calls_made),
        )

        should_escalate = await self._should_escalate(agent, full_response_text, messages)
        if should_escalate:
            session.status = "escalated"

        yield StreamChatEvent(
            type="done",
            data={
                "session_id": session_id,
                "latency_ms": latency_ms,
                "tokens_used": total_tokens,
                "tool_calls_made": len(tool_calls_made),
                "escalate_to_human": should_escalate,
            },
            session_id=session_id,
        )

    async def _build_system_prompt(
        self, agent: Agent, context_items: list
    ) -> str:
        """Build dynamic system prompt with business context."""
        return build_system_prompt(
            agent=agent,
            context_items=context_items,
            business_info={},
        )

    async def _should_escalate(
        self, agent: Agent, response: str, messages: list
    ) -> bool:
        """
        Determine if the conversation should be escalated to a human.
        Checks:
        1. Agent escalation config
        2. Keywords in the LLM's response indicating inability to help
        3. Repeated user frustration signals in recent messages
        """
        escalation_config = agent.escalation_config or {}
        if not escalation_config.get("escalate_to_human", False):
            return False

        # Check if assistant response suggests escalation
        response_lower = response.lower()
        for keyword in ESCALATION_KEYWORDS:
            if keyword.lower() in response_lower:
                return True

        # Check last 3 user messages for repeated frustration
        user_messages = [
            m["content"] for m in messages
            if m.get("role") == "user"
        ][-3:]

        frustration_count = 0
        frustration_signals = ["again", "still", "not working", "doesn't help", "useless", "terrible"]
        for msg in user_messages:
            for signal in frustration_signals:
                if signal in msg.lower():
                    frustration_count += 1

        return frustration_count >= 2

    async def _get_agent_tools_schema(
        self, agent: Agent, tenant_id: str
    ) -> list[dict]:
        """
        Retrieve OpenAI-format tool schemas from MCP server for the tools
        enabled on this agent.
        """
        enabled_tools = agent.tools or []
        if not enabled_tools:
            return []

        schemas = await self.mcp.get_tool_schemas(
            tenant_id=tenant_id,
            tool_names=enabled_tools,
        )
        return schemas

    async def _execute_tool_calls(
        self,
        tool_calls: list[ToolCall],
        tenant_id: str,
        session_id: str,
    ) -> list[dict]:
        """
        Execute all tool calls in parallel via the MCP client.
        Returns a list of results in the same order as the input tool_calls.
        """
        trace_id = str(uuid.uuid4())
        tasks = [
            self.mcp.execute_tool(
                tenant_id=tenant_id,
                tool_name=tc.name,
                parameters=tc.arguments,
                session_id=session_id,
                trace_id=f"{trace_id}-{i}",
            )
            for i, tc in enumerate(tool_calls)
        ]
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

    async def _update_analytics(
        self,
        tenant_id,
        agent_id,
        tokens: int,
        latency_ms: int,
        tool_count: int,
        escalated: bool = False,
        completed: bool = True,
    ):
        """
        Upsert today's analytics record for this agent.
        Uses INSERT ... ON CONFLICT DO UPDATE pattern via SQLAlchemy.
        """
        try:
            today = date.today()
            result = await self.db.execute(
                select(AgentAnalytics).where(
                    and_(
                        AgentAnalytics.tenant_id == tenant_id,
                        AgentAnalytics.agent_id == agent_id,
                        AgentAnalytics.date == today,
                    )
                )
            )
            analytics = result.scalar_one_or_none()

            if analytics is None:
                analytics = AgentAnalytics(
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                    date=today,
                    total_sessions=0,
                    total_messages=1,
                    avg_response_latency_ms=float(latency_ms),
                    total_tokens_used=tokens,
                    estimated_cost_usd=self._estimate_cost(tokens),
                    tool_executions=tool_count,
                    escalations=1 if escalated else 0,
                    successful_completions=1 if completed else 0,
                )
                self.db.add(analytics)
            else:
                analytics.total_messages += 1
                analytics.total_tokens_used += tokens
                analytics.estimated_cost_usd += self._estimate_cost(tokens)
                analytics.tool_executions += tool_count
                if escalated:
                    analytics.escalations += 1
                if completed:
                    analytics.successful_completions += 1
                # Rolling average for latency
                n = analytics.total_messages
                analytics.avg_response_latency_ms = (
                    (analytics.avg_response_latency_ms * (n - 1) + latency_ms) / n
                )
        except Exception as exc:
            logger.error("analytics_update_error", error=str(exc))

    def _estimate_cost(self, tokens: int) -> float:
        """
        Rough cost estimate in USD.
        Gemini Flash: ~$0.075 per 1M tokens (input) / $0.30 per 1M (output)
        Approximation: $0.0001 per 1K tokens
        """
        return (tokens / 1000) * 0.0001

    async def _build_escalation_response(
        self,
        agent: Agent,
        session: AgentSession,
        user_message: str,
        start_time: float,
    ) -> ChatResponse:
        """Build a response when immediate escalation is needed."""
        escalation_config = agent.escalation_config or {}
        escalation_number = escalation_config.get("escalation_number", "")

        if escalation_number:
            message = (
                f"I'll connect you with a human agent right away. "
                f"You can also reach them directly at {escalation_number}."
            )
        else:
            message = "I'll connect you with a human agent right away. Please hold on."

        session.status = "escalated"
        latency_ms = int((time.monotonic() - start_time) * 1000)

        # Save the interaction
        self.db.add(Message(
            session_id=session.id,
            tenant_id=session.tenant_id,
            role="user",
            content=user_message,
            tokens_used=0,
            latency_ms=0,
        ))
        self.db.add(Message(
            session_id=session.id,
            tenant_id=session.tenant_id,
            role="assistant",
            content=message,
            tokens_used=0,
            latency_ms=latency_ms,
        ))

        return ChatResponse(
            session_id=session.id,
            message=message,
            tool_calls_made=[],
            suggested_actions=[],
            escalate_to_human=True,
            latency_ms=latency_ms,
            tokens_used=0,
        )

    def _extract_suggested_actions(self, response: str, intent: str) -> list[str]:
        """
        Extract or generate suggested follow-up actions based on the response and intent.
        """
        suggestions: list[str] = []
        response_lower = response.lower()

        intent_suggestions = {
            "order_food": ["Track my order", "Modify my order", "Cancel order"],
            "book_appointment": ["View my appointments", "Cancel appointment", "Reschedule"],
            "status_check": ["View order history", "Contact support"],
            "pricing": ["Place an order", "View full menu", "Get a quote"],
            "complaint": ["Speak to a manager", "Request a refund", "Track resolution"],
            "greeting": ["View services", "Make a booking", "Check prices"],
        }

        if intent in intent_suggestions:
            suggestions = intent_suggestions[intent][:2]

        # Add escalation suggestion if response hints at limitations
        if any(phrase in response_lower for phrase in ["i'm not able", "cannot help", "beyond my"]):
            if "Speak to a human agent" not in suggestions:
                suggestions.append("Speak to a human agent")

        return suggestions
