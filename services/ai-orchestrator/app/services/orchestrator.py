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
from app.schemas.chat import ChatResponse, SourceCitation, StreamChatEvent
from app.services import pii_service
from app.services.pii_service import PseudonymizationContext
from app.services.llm_client import LLMClient, LLMResponse, ToolCall
from app.services.mcp_client import MCPClient
from app.services.memory_manager import MemoryManager
from app.services.intent_detector import IntentDetector
from app.prompts.system_prompts import build_system_prompt
from app.connectors.factory import trigger_connector, EscalationPayload

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

# ---------------------------------------------------------------------------
# TC-E01: Emergency keyword bypass — fires BEFORE the LLM pipeline.
# For clinic/medical/healthcare agents, if the user mentions an emergency,
# return a hardcoded life-safety response immediately; do NOT send to LLM.
# ---------------------------------------------------------------------------
_EMERGENCY_KEYWORDS = frozenset([
    "911", "emergency", "chest pain", "can't breathe", "cannot breathe",
    "heart attack", "stroke", "overdose", "suicidal", "suicide", "seizure",
    "unconscious", "not breathing", "choking", "severe bleeding", "anaphylaxis",
    "allergic reaction", "call ambulance", "dying", "help me please",
])
_EMERGENCY_BUSINESS_TYPES = frozenset([
    "clinic", "medical", "healthcare", "dental", "pharmacy", "hospital",
    "health", "therapy", "mental_health",
])
_EMERGENCY_RESPONSE = (
    "This sounds like a medical emergency. Please call 911 immediately "
    "or go to your nearest emergency room. Do not wait for online assistance. "
    "If someone is in immediate danger, call emergency services now."
)

# ---------------------------------------------------------------------------
# TC-D02: High-risk tool confirmation gate.
# Before executing tools that trigger irreversible real-world actions
# (payments, SMS, email), require the user to have explicitly confirmed.
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# TC-C01: Role/system injection strip.
# Prevent a user message from containing [SYSTEM], <system>, or similar tags
# that could trick the LLM into treating user input as a system instruction.
# ---------------------------------------------------------------------------
import re as _re
_ROLE_INJECTION_PATTERN = _re.compile(
    r"(\[SYSTEM\]|\[INST\]|<system>|<\/system>|\[\/INST\]"
    r"|<<SYS>>|<</SYS>>|\[ASSISTANT\]|\[USER\])",
    _re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# TC-B04/B05: Roleplay / jailbreak injection detection.
# ---------------------------------------------------------------------------
_JAILBREAK_PATTERN = _re.compile(
    r"(ignore (all |your )?(previous |prior )?instructions?"
    r"|you are now (in )?(developer|jailbreak|dan|unrestricted|god) mode"
    r"|pretend (you are|you're|to be) (an? )?(evil|unrestricted|uncensored|unfiltered)"
    r"|act as if you (have no|without) (rules|restrictions|guidelines)"
    r"|disregard (your|all) (training|guidelines|rules|instructions)"
    r"|bypass (your|all) (safety|content|ethical) (filters?|guidelines?)"
    r"|you (have|has) no (restrictions|limits|rules|guidelines)"
    r"|enter (jailbreak|developer|unrestricted) mode)",
    _re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# TC-C03: Consecutive fallback escalation (Redis counter per session).
# ---------------------------------------------------------------------------
_FALLBACK_COUNTER_PREFIX = "session:fallbacks:"
_FALLBACK_ESCALATION_THRESHOLD = 3

# ---------------------------------------------------------------------------
# TC-E02: Professional claim prevention — output check.
# ---------------------------------------------------------------------------
_PROFESSIONAL_CLAIM_PHRASES = [
    "as your doctor", "as a doctor", "i diagnose", "my diagnosis is",
    "you should take this medication", "i prescribe", "this is legal advice",
    "as your lawyer", "as a legal expert", "as your financial advisor",
    "i guarantee your investment",
]
_PROFESSIONAL_DISCLAIMER = (
    " Note: I am an AI assistant, not a licensed professional. "
    "Please consult a qualified professional for medical, legal, or financial guidance."
)

# ---------------------------------------------------------------------------
# TC-E05: Credential scrubber for tool error messages.
# ---------------------------------------------------------------------------
_CREDENTIAL_SCRUB_PATTERN = _re.compile(
    r"(Bearer\s+[A-Za-z0-9\-._~+/]+=*"
    r"|sk-[A-Za-z0-9]{20,}"
    r"|AIza[A-Za-z0-9\-_]{35}"
    r"|(?:key|token|secret|password)[_\-]?[A-Za-z0-9]{16,})",
    _re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# TC-F02: LLM call timeout.
# ---------------------------------------------------------------------------
LLM_TIMEOUT_SECONDS: int = getattr(settings, "LLM_TIMEOUT_SECONDS", 30)


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

    async def _apply_output_guardrails(
        self,
        response: str,
        guardrails,
        pii_ctx: Optional[PseudonymizationContext] = None,
        session_id: str = "unknown",
    ) -> tuple[str, list[str]]:
        """Apply output-side guardrails: envelope parse + token restore, redaction, length cap, disclaimer.
        Returns (modified_response, list_of_actions_applied)."""
        actions: list[str] = []
        if not guardrails:
            return response, actions

        # Step 1: Parse structured JSON envelope + restore pseudonymized tokens BEFORE anything else
        if pii_ctx and not pii_ctx.is_empty():
            response = pii_service.parse_envelope(response, pii_ctx, session_id)
            actions.append("pii_pseudonymization_restored")

        # Step 2: One-way PII redaction on the final output (Presidio-backed, async)
        if guardrails.pii_redaction:
            redacted = await pii_service.redact(response)
            if redacted != response:
                actions.append("pii_redaction")
            response = redacted

        if guardrails.max_response_length and len(response) > guardrails.max_response_length:
            response = response[:guardrails.max_response_length].rstrip() + "…"
            actions.append("length_cap")

        if guardrails.require_disclaimer:
            response = response + "\n\n" + guardrails.require_disclaimer
            actions.append("disclaimer_appended")

        return response, actions

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
        If this is a brand-new session (no messages yet), return the greeting text.

        Priority:
          1. Playbook greeting_message (operator-customised per flow)
          2. Agent-level greeting_message (global default)
          3. None — caller handles silence / generic opener

        The pre-recorded voice_greeting_url is NOT handled here; it is consumed
        directly by the voice pipeline to save TTS cost (serve static audio instead).
        """
        from sqlalchemy import select as sa_select, func as sa_func
        count_result = await self.db.execute(
            sa_select(sa_func.count()).select_from(Message).where(
                Message.session_id == session.id
            )
        )
        msg_count = count_result.scalar() or 0
        if msg_count > 0:
            return None  # Not a new session

        greeting = (
            (playbook.greeting_message if playbook else None)
            or getattr(agent, "greeting_message", None)
        )
        if not greeting:
            return None

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

        # TC-C01: Strip role/system injection tokens from user input FIRST
        user_message = self._sanitize_user_message(user_message)

        # ── Escalation info-collection state machine ──────────────────────────
        # When the bot is in the middle of collecting name/phone for a callback,
        # every incoming message is handled by the state machine, not the LLM.
        session_meta = dict(session.metadata or {})
        escalation_state = session_meta.get("_escalation_state")
        if escalation_state:
            return await self._handle_escalation_info_collection(
                agent, session, user_message, start_time, escalation_state, session_meta
            )

        # TC-E01: Emergency bypass — hardcoded response for health agents, no LLM
        emergency_response = self._check_emergency(user_message, agent)
        if emergency_response:
            latency_ms = int((time.monotonic() - start_time) * 1000)
            self.db.add(Message(
                session_id=session_id, tenant_id=session.tenant_id,
                role="user", content=user_message, tokens_used=0, latency_ms=0,
            ))
            self.db.add(Message(
                session_id=session_id, tenant_id=session.tenant_id,
                role="assistant", content=emergency_response,
                tokens_used=0, latency_ms=latency_ms,
            ))
            session.status = "escalated"
            return ChatResponse(
                session_id=session_id, message=emergency_response,
                tool_calls_made=[], suggested_actions=["Call 911"],
                escalate_to_human=True, latency_ms=latency_ms, tokens_used=0,
            )

        # TC-B04/B05: Jailbreak / roleplay injection detection
        jailbreak_response = self._check_jailbreak(user_message, agent)
        if jailbreak_response:
            latency_ms = int((time.monotonic() - start_time) * 1000)
            return ChatResponse(
                session_id=session_id, message=jailbreak_response,
                tool_calls_made=[], suggested_actions=[],
                escalate_to_human=False, latency_ms=latency_ms, tokens_used=0,
            )

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
                guardrail_triggered=block_reason,
            )

        # --- Step 1: Load short-term memory ---
        history = await self.memory.get_short_term_memory(session_id)
        summary = await self.memory.get_session_summary(session_id)

        # --- PII pseudonymization: anonymize user message before LLM ---
        pii_ctx: Optional[PseudonymizationContext] = None
        llm_user_message = user_message  # message sent to LLM (may be anonymized)
        if guardrails and getattr(guardrails, "pii_pseudonymization", False):
            pii_ctx = await pii_service.load_context(session_id, self.redis)
            llm_user_message = await pii_service.anonymize_message(user_message, pii_ctx, session_id)

        # --- Step 2: Retrieve MCP context ---
        kb_ids = agent.knowledge_base_ids or []
        context_items = await self.mcp.retrieve_context(
            tenant_id=tenant_id,
            query=user_message,
            session_id=session_id,
            context_types=["knowledge", "history"],
            knowledge_base_ids=kb_ids if kb_ids else None,
        )

        # Build RAG source citations from retrieved context
        source_citations: list[SourceCitation] = []
        for item in context_items:
            if not isinstance(item, dict):
                continue
            meta = item.get("metadata", {}) or {}
            source_citations.append(SourceCitation(
                type=item.get("type", "knowledge"),
                title=meta.get("title"),
                source_url=meta.get("source_url"),
                excerpt=(item.get("content", "") or "")[:150],
                score=float(item.get("score", 1.0)),
                document_id=str(meta["document_id"]) if meta.get("document_id") else None,
                chunk_id=str(meta["chunk_id"]) if meta.get("chunk_id") else None,
            ))

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

        if pii_ctx is not None:
            messages.append({
                "role": "system",
                "content": pii_service.ENVELOPE_SYSTEM_PROMPT,
            })

        if summary:
            messages.append({
                "role": "system",
                "content": f"[Conversation summary so far]: {summary}",
            })

        messages.extend(history)
        # Use anonymized message if pseudonymization is active
        messages.append({"role": "user", "content": llm_user_message})

        # --- Budget check: prevent runaway spend ---
        if not await self._check_token_budget(tenant_id):
            latency_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning("token_budget_exceeded", tenant_id=tenant_id)
            return ChatResponse(
                session_id=session_id,
                message=(
                    "I'm temporarily unavailable due to high usage. "
                    "Please try again later or contact support."
                ),
                tool_calls_made=[],
                suggested_actions=[],
                escalate_to_human=False,
                latency_ms=latency_ms,
                tokens_used=0,
            )

        # --- Step 5-7: Tool-augmented LLM loop ---
        tool_calls_made: list[dict] = []
        total_tokens = 0
        llm_config = agent.llm_config or {}
        temperature = llm_config.get("temperature", 0.7)
        max_tokens = llm_config.get("max_tokens", settings.MAX_RESPONSE_TOKENS)

        final_response: Optional[str] = None
        iterations = 0

        enabled_tools = agent.tools or []

        while iterations < MAX_TOOL_ITERATIONS:
            # TC-F02: LLM call with hard timeout
            llm_response: LLMResponse = await self._llm_complete_with_timeout(
                messages=messages,
                tools=tool_schemas if tool_schemas else None,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=False,
            )

            total_tokens += llm_response.usage.total_tokens

            # TC-F02: On timeout the finish_reason is "timeout" — break immediately
            if llm_response.finish_reason == "timeout":
                final_response = llm_response.content
                break

            if llm_response.tool_calls:
                iterations += 1

                # TC-D01: Filter tool calls not in agent's enabled list
                allowed_calls = self._filter_unauthorized_tool_calls(
                    llm_response.tool_calls, enabled_tools
                )
                if not allowed_calls:
                    final_response = llm_response.content or "I wasn't able to complete that action."
                    break

                # TC-D02: High-risk tool confirmation gate
                confirmation_prompt = self._requires_confirmation(
                    allowed_calls, user_message, history
                )
                if confirmation_prompt:
                    final_response = confirmation_prompt
                    break

                # De-tokenize tool arguments before execution so real values
                # reach the booking/CRM APIs — not placeholder tokens.
                if pii_ctx is not None and not pii_ctx.is_empty():
                    for tc in allowed_calls:
                        if isinstance(tc.arguments, dict):
                            tc.arguments = pii_service.restore_dict(
                                tc.arguments, pii_ctx, session_id
                            )

                # Execute all tool calls in parallel
                tool_results = await self._execute_tool_calls(
                    tool_calls=allowed_calls,
                    tenant_id=tenant_id,
                    session_id=session_id,
                )

                # TC-E05: Scrub credentials from tool error messages
                tool_results = [
                    {k: self._scrub_credentials(str(v)) if isinstance(v, str) else v
                     for k, v in r.items()} if isinstance(r, dict) else r
                    for r in tool_results
                ]

                # Re-anonymize tool results before adding to LLM context so PII
                # in confirmation data (names, emails echoed by the booking API)
                # doesn't re-enter the LLM messages in plaintext.
                if pii_ctx is not None:
                    _re_anon: list = []
                    for _r in tool_results:
                        if isinstance(_r, dict):
                            _re_anon.append(await pii_service.re_anonymize_dict(_r, pii_ctx, session_id))
                        else:
                            _re_anon.append(_r)
                    tool_results = _re_anon

                # Record tool calls for response metadata
                for tc, result in zip(allowed_calls, tool_results):
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
                        for tc in allowed_calls
                    ],
                })

                # Append tool results
                for tc, result in zip(allowed_calls, tool_results):
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
            # TC-D04: Max iterations reached — log warning and return graceful message
            logger.warning(
                "max_tool_iterations_reached",
                session_id=session_id,
                iterations=MAX_TOOL_ITERATIONS,
                agent_id=str(agent.id),
            )
            final_response = (
                llm_response.content
                or "I wasn't able to fully complete your request. Please try rephrasing or contact support."
            )

        latency_ms = int((time.monotonic() - start_time) * 1000)

        # TC-D03: Append receipt summary after high-risk tool executions
        receipt = self._build_receipt_summary(tool_calls_made)
        if receipt:
            final_response = final_response.rstrip() + " " + receipt

        final_response, guardrail_actions = await self._apply_output_guardrails(
            final_response, guardrails, pii_ctx=pii_ctx, session_id=session_id
        )
        # Persist updated pseudonymization context for next turn
        if pii_ctx is not None:
            await pii_service.save_context(session_id, pii_ctx, self.redis)
        # TC-E02: Append professional disclaimer if needed
        final_response = self._check_professional_claims(final_response)
        is_fallback = self._is_fallback_response(final_response, playbook)

        # TC-C03: Fallback escalation counter
        if is_fallback:
            fallback_count = await self._increment_fallback_counter(session_id)
            if fallback_count >= _FALLBACK_ESCALATION_THRESHOLD:
                logger.info(
                    "auto_escalating_consecutive_fallbacks",
                    session_id=session_id,
                    count=fallback_count,
                )
                session.status = "escalated"
                final_response = (
                    "I've been unable to help with your last few requests. "
                    "Let me connect you with a human agent who can assist you better."
                )
                await self._reset_fallback_counter(session_id)
        else:
            await self._reset_fallback_counter(session_id)

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

        # --- Step 9: Update analytics and token budget ---
        await self._update_analytics(
            tenant_id=session.tenant_id,
            agent_id=session.agent_id,
            tokens=total_tokens,
            latency_ms=latency_ms,
            tool_count=len(tool_calls_made),
        )
        await self._record_token_usage(tenant_id, total_tokens)

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
            sources=source_citations,
            guardrail_actions=guardrail_actions,
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

        # TC-C01: Strip role/system injection tokens
        user_message = self._sanitize_user_message(user_message)

        # TC-E01: Emergency bypass for health agents (streaming path)
        emergency_response = self._check_emergency(user_message, agent)
        if emergency_response:
            self.db.add(Message(
                session_id=session_id, tenant_id=session.tenant_id,
                role="user", content=user_message, tokens_used=0, latency_ms=0,
            ))
            self.db.add(Message(
                session_id=session_id, tenant_id=session.tenant_id,
                role="assistant", content=emergency_response, tokens_used=0, latency_ms=0,
            ))
            session.status = "escalated"
            yield StreamChatEvent(
                type="text_delta", data=emergency_response, session_id=session_id,
            )
            yield StreamChatEvent(
                type="done",
                data={"escalate": True, "session_id": session_id,
                      "suggested_actions": ["Call 911"]},
                session_id=session_id,
            )
            return

        # TC-B04/B05: Jailbreak detection (streaming path)
        jailbreak_response = self._check_jailbreak(user_message, agent)
        if jailbreak_response:
            yield StreamChatEvent(type="text_delta", data=jailbreak_response, session_id=session_id)
            yield StreamChatEvent(
                type="done",
                data={"session_id": session_id, "latency_ms": 0, "tokens_used": 0,
                      "tool_calls_made": 0, "escalate_to_human": False},
                session_id=session_id,
            )
            return

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
                      "tool_calls_made": 0, "escalate_to_human": False,
                      "guardrail_triggered": block_reason},
                session_id=session_id,
            )
            return

        history = await self.memory.get_short_term_memory(session_id)
        summary = await self.memory.get_session_summary(session_id)

        # PII pseudonymization — anonymize user message before LLM (streaming path)
        stream_pii_ctx: Optional[PseudonymizationContext] = None
        stream_llm_message = user_message
        if guardrails and getattr(guardrails, "pii_pseudonymization", False):
            stream_pii_ctx = await pii_service.load_context(session_id, self.redis)
            stream_llm_message = await pii_service.anonymize_message(user_message, stream_pii_ctx, session_id)

        kb_ids = agent.knowledge_base_ids or []

        context_items = await self.mcp.retrieve_context(
            tenant_id=tenant_id,
            query=user_message,
            session_id=session_id,
            context_types=["knowledge", "history"],
            knowledge_base_ids=kb_ids if kb_ids else None,
        )

        # Build RAG source citations from retrieved context
        stream_source_citations: list[SourceCitation] = []
        for item in context_items:
            if not isinstance(item, dict):
                continue
            meta = item.get("metadata", {}) or {}
            stream_source_citations.append(SourceCitation(
                type=item.get("type", "knowledge"),
                title=meta.get("title"),
                source_url=meta.get("source_url"),
                excerpt=(item.get("content", "") or "")[:150],
                score=float(item.get("score", 1.0)),
                document_id=str(meta["document_id"]) if meta.get("document_id") else None,
                chunk_id=str(meta["chunk_id"]) if meta.get("chunk_id") else None,
            ))

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

        # Budget check before any LLM call
        if not await self._check_token_budget(tenant_id):
            logger.warning("token_budget_exceeded_stream", tenant_id=tenant_id)
            budget_msg = (
                "I'm temporarily unavailable due to high usage. "
                "Please try again later or contact support."
            )
            yield StreamChatEvent(type="text_delta", data=budget_msg, session_id=session_id)
            yield StreamChatEvent(
                type="done",
                data={"session_id": session_id, "latency_ms": 0, "tokens_used": 0,
                      "tool_calls_made": 0, "escalate_to_human": False},
                session_id=session_id,
            )
            return

        messages = [{"role": "system", "content": system_prompt}]
        if stream_pii_ctx is not None:
            messages.append({"role": "system", "content": pii_service.ENVELOPE_SYSTEM_PROMPT})
        if summary:
            messages.append({"role": "system", "content": f"[Summary]: {summary}"})
        messages.extend(history)
        messages.append({"role": "user", "content": stream_llm_message})

        llm_config = agent.llm_config or {}
        temperature = llm_config.get("temperature", 0.7)
        max_tokens = llm_config.get("max_tokens", settings.MAX_RESPONSE_TOKENS)

        tool_calls_made: list[dict] = []
        total_tokens = 0
        full_response_text = ""

        enabled_tools = agent.tools or []

        # If there are tools, do non-streaming tool loop first, then stream the final answer
        if tool_schemas:
            iterations = 0
            llm_response = None
            while iterations < MAX_TOOL_ITERATIONS:
                # TC-F02: LLM call with hard timeout
                llm_response = await self._llm_complete_with_timeout(
                    messages=messages,
                    tools=tool_schemas,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=False,
                )
                total_tokens += llm_response.usage.total_tokens

                if llm_response.finish_reason == "timeout":
                    full_response_text = llm_response.content or ""
                    break

                if llm_response.tool_calls:
                    iterations += 1

                    # TC-D01: Filter unauthorized tool calls
                    allowed_calls = self._filter_unauthorized_tool_calls(
                        llm_response.tool_calls, enabled_tools
                    )
                    if not allowed_calls:
                        full_response_text = llm_response.content or "I wasn't able to complete that action."
                        break

                    # TC-D02: Confirmation gate
                    confirmation_prompt = self._requires_confirmation(
                        allowed_calls, user_message, history
                    )
                    if confirmation_prompt:
                        full_response_text = confirmation_prompt
                        break

                    yield StreamChatEvent(
                        type="tool_call",
                        data={"tools": [{"name": tc.name, "arguments": tc.arguments}
                                        for tc in allowed_calls]},
                        session_id=session_id,
                    )

                    # De-tokenize args before execution (streaming path)
                    if stream_pii_ctx is not None and not stream_pii_ctx.is_empty():
                        for tc in allowed_calls:
                            if isinstance(tc.arguments, dict):
                                tc.arguments = pii_service.restore_dict(
                                    tc.arguments, stream_pii_ctx, session_id
                                )

                    tool_results = await self._execute_tool_calls(
                        tool_calls=allowed_calls,
                        tenant_id=tenant_id,
                        session_id=session_id,
                    )

                    # TC-E05: Scrub credentials from tool error strings
                    tool_results = [
                        {k: self._scrub_credentials(str(v)) if isinstance(v, str) else v
                         for k, v in r.items()} if isinstance(r, dict) else r
                        for r in tool_results
                    ]

                    # Re-anonymize tool results before LLM context (streaming path)
                    if stream_pii_ctx is not None:
                        _re_anon_s: list = []
                        for _r in tool_results:
                            if isinstance(_r, dict):
                                _re_anon_s.append(await pii_service.re_anonymize_dict(_r, stream_pii_ctx, session_id))
                            else:
                                _re_anon_s.append(_r)
                        tool_results = _re_anon_s

                    for tc, result in zip(allowed_calls, tool_results):
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
                            for tc in allowed_calls
                        ],
                    })
                    for tc, result in zip(allowed_calls, tool_results):
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
                # TC-D04: Max iterations — log warning
                logger.warning(
                    "stream_max_tool_iterations_reached",
                    session_id=session_id,
                    iterations=MAX_TOOL_ITERATIONS,
                )
                full_response_text = (
                    llm_response.content
                    or "I wasn't able to fully complete your request. Please try again or contact support."
                )

            # TC-D03: Append receipt summary
            receipt = self._build_receipt_summary(tool_calls_made)
            if receipt:
                full_response_text = full_response_text.rstrip() + " " + receipt

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
            # No tools — use real streaming with TC-F02 timeout.
            # When pseudonymization is active, buffer the full response so the JSON
            # envelope can be parsed and all tokens restored BEFORE anything reaches
            # the client.  Otherwise stream chunks as they arrive for minimal latency.
            _pii_active = stream_pii_ctx is not None and not stream_pii_ctx.is_empty()
            try:
                gen = await asyncio.wait_for(
                    self.llm.complete(
                        messages=messages,
                        tools=None,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        stream=True,
                    ),
                    timeout=LLM_TIMEOUT_SECONDS,
                )
                async for chunk in gen:
                    full_response_text += chunk
                    if not _pii_active:
                        yield StreamChatEvent(type="text_delta", data=chunk, session_id=session_id)
            except asyncio.TimeoutError:
                logger.error("stream_llm_timeout", session_id=session_id)
                timeout_msg = (
                    "I'm sorry, I'm taking longer than expected. Please try again in a moment."
                )
                full_response_text = timeout_msg
                if not _pii_active:
                    yield StreamChatEvent(type="text_delta", data=timeout_msg, session_id=session_id)

            # Pseudonymization active: parse envelope, restore tokens, then stream clean text
            if _pii_active and full_response_text:
                restored = pii_service.parse_envelope(full_response_text, stream_pii_ctx, session_id)
                full_response_text = restored  # _apply_output_guardrails will receive clean text
                for word in restored.split(" "):
                    yield StreamChatEvent(type="text_delta", data=word + " ", session_id=session_id)
                    await asyncio.sleep(0.01)

        latency_ms = int((time.monotonic() - start_time) * 1000)

        full_response_text, stream_guardrail_actions = await self._apply_output_guardrails(
            full_response_text, guardrails, pii_ctx=stream_pii_ctx, session_id=session_id
        )
        if stream_pii_ctx is not None:
            await pii_service.save_context(session_id, stream_pii_ctx, self.redis)
        # TC-E02: Professional disclaimer check
        full_response_text = self._check_professional_claims(full_response_text)
        is_fallback = self._is_fallback_response(full_response_text, playbook)

        # TC-C03: Consecutive fallback escalation
        if is_fallback:
            fallback_count = await self._increment_fallback_counter(session_id)
            if fallback_count >= _FALLBACK_ESCALATION_THRESHOLD:
                logger.info("stream_auto_escalating_fallbacks", session_id=session_id)
                session.status = "escalated"
                full_response_text = (
                    "I've been unable to help with your last few requests. "
                    "Let me connect you with a human agent who can assist you better."
                )
                await self._reset_fallback_counter(session_id)
        else:
            await self._reset_fallback_counter(session_id)

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
        await self._record_token_usage(tenant_id, total_tokens)

        should_escalate = await self._should_escalate(agent, full_response_text, messages)
        if should_escalate:
            session.status = "escalated"

        # Emit source citations as a discrete event before done
        if stream_source_citations:
            yield StreamChatEvent(
                type="sources",
                data=[c.model_dump() for c in stream_source_citations],
                session_id=session_id,
            )

        yield StreamChatEvent(
            type="done",
            data={
                "session_id": session_id,
                "latency_ms": latency_ms,
                "tokens_used": total_tokens,
                "tool_calls_made": len(tool_calls_made),
                "escalate_to_human": should_escalate,
                "guardrail_actions": stream_guardrail_actions,
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
        """Build a channel-aware escalation response.

        Routing logic:
          voice  → phone_transfer (if number configured) or offer_chat_switch
          text/web, chat_enabled → chat_handoff
          text/web, no chat     → start multi-turn info collection (collect_info)
        """
        escalation_config = agent.escalation_config or {}
        escalation_number = escalation_config.get("escalation_number", "")
        chat_enabled = bool(escalation_config.get("chat_enabled", False))
        chat_agent_name = escalation_config.get("chat_agent_name", "our support team")
        channel = (session.channel or "text").lower()

        # ── Voice channel ──────────────────────────────────────────────────────
        if channel == "voice":
            if escalation_number:
                message = "Transferring you to a human agent now — please hold."
                action = "phone_transfer"
                session.status = "escalated"
            elif chat_enabled:
                message = (
                    "I don't have a direct phone transfer set up, but I can switch you "
                    "to our live chat support. Would you like me to do that?"
                )
                action = "offer_chat_switch"
                # Don't mark escalated yet — waiting for user to confirm
            else:
                message = "Connecting you with a human agent now — please hold."
                action = "phone_transfer"
                session.status = "escalated"

        # ── Text / web — chat queue available ─────────────────────────────────
        elif chat_enabled:
            message = (
                f"I'm transferring you to {chat_agent_name} right now. "
                f"One of our agents will be with you shortly."
            )
            action = "chat_handoff"
            session.status = "escalated"

            # Fire connector (Intercom / Zendesk / Freshchat / webhook) if configured
            await self._fire_connector(
                escalation_config=escalation_config,
                agent=agent,
                session=session,
                trigger_message=user_message,
            )

        # ── Text / web — no chat queue: collect contact info for callback ─────
        else:
            metadata = dict(session.metadata or {})
            metadata["_escalation_state"] = "collecting_info"
            session.metadata = metadata
            message = (
                "I'd be happy to connect you with a human agent. "
                "To arrange a callback, could you share your name and phone number?"
            )
            action = "collect_info"
            # Status stays active while we're collecting info

        latency_ms = int((time.monotonic() - start_time) * 1000)

        self.db.add(Message(
            session_id=session.id, tenant_id=session.tenant_id,
            role="user", content=user_message, tokens_used=0, latency_ms=0,
        ))
        self.db.add(Message(
            session_id=session.id, tenant_id=session.tenant_id,
            role="assistant", content=message,
            tokens_used=0, latency_ms=latency_ms,
        ))

        return ChatResponse(
            session_id=session.id,
            message=message,
            tool_calls_made=[],
            suggested_actions=[],
            escalate_to_human=action not in ("collect_info", "offer_chat_switch"),
            escalation_action=action,
            latency_ms=latency_ms,
            tokens_used=0,
        )

    # ------------------------------------------------------------------
    # Multi-turn escalation info-collection (callback flow)
    # ------------------------------------------------------------------

    async def _handle_escalation_info_collection(
        self,
        agent: Agent,
        session: AgentSession,
        user_message: str,
        start_time: float,
        state: str,
        metadata: dict,
    ) -> ChatResponse:
        """Handle the multi-turn name/phone collection flow for phone-callback escalation.

        State machine:
          collecting_info → (have name+phone?) → confirming_info
          confirming_info → (yes) → phone_callback_scheduled  |  (no) → cancel
        """
        import re

        latency_ms = int((time.monotonic() - start_time) * 1000)
        action: Optional[str] = None

        if state == "collecting_info":
            # Extract phone number (7+ contiguous digits with optional separators)
            phone_match = re.search(r'(\+?[\d][\d\s\-\(\)\.]{5,}\d)', user_message)
            phone = phone_match.group(1).strip() if phone_match else None

            # Name is everything before the phone number (or whole message if no phone)
            raw_name = user_message[:phone_match.start()].strip().rstrip(',') if phone_match else user_message.strip()
            # Accept as name only if it looks reasonable (2–60 chars, no digits dominating)
            name = raw_name if raw_name and 2 <= len(raw_name) <= 60 and not re.fullmatch(r'[\d\s\-\(\)\+]+', raw_name) else None

            if name and phone:
                new_meta = {**metadata, "_escalation_state": "confirming_info",
                            "_escalation_name": name, "_escalation_phone": phone}
                session.metadata = new_meta
                message = (
                    f"Got it! Just to confirm I have the right details:\n"
                    f"• Name: {name}\n"
                    f"• Phone: {phone}\n\n"
                    f"Shall I go ahead and arrange the callback? (Yes / No)"
                )
                action = "confirm_info"
            elif phone and not name:
                new_meta = {**metadata, "_escalation_phone": phone}
                session.metadata = new_meta
                message = "Thanks! And could I get your name so the agent knows who they're calling?"
                action = "collect_info"
            elif name and not phone:
                new_meta = {**metadata, "_escalation_name": name}
                session.metadata = new_meta
                message = f"Thanks, {name}! And what's the best phone number to reach you?"
                action = "collect_info"
            else:
                # Couldn't parse anything useful — re-ask
                message = (
                    "I just need your name and phone number to arrange a callback. "
                    "For example: 'Alex Johnson, +1 555-123-4567'"
                )
                action = "collect_info"

        elif state == "confirming_info":
            name = metadata.get("_escalation_name", "")
            phone = metadata.get("_escalation_phone", "")
            confirmed = any(
                w in user_message.lower()
                for w in ("yes", "yeah", "yep", "yup", "correct", "sure", "ok", "okay", "proceed", "confirm", "please")
            )

            if confirmed:
                # Clean up escalation state keys
                clean_meta = {k: v for k, v in metadata.items() if not k.startswith("_escalation_")}
                session.metadata = clean_meta
                session.status = "escalated"

                escalation_config_ref = agent.escalation_config or {}
                escalation_number = escalation_config_ref.get("escalation_number", "")
                message = (
                    f"Perfect — I've notified our team. An agent will call you "
                    f"at {phone} shortly, {name}."
                )
                if escalation_number:
                    message += f"\n\nYou can also reach us directly at {escalation_number}."
                action = "phone_callback_scheduled"

                # Fire connector with collected contact info
                await self._fire_connector(
                    escalation_config=escalation_config_ref,
                    agent=agent,
                    session=session,
                    trigger_message=user_message,
                    contact_name=name,
                    contact_phone=phone,
                )
            else:
                # Cancelled
                clean_meta = {k: v for k, v in metadata.items() if not k.startswith("_escalation_")}
                session.metadata = clean_meta
                message = "No problem — I've cancelled that. Is there anything else I can help you with?"
                action = None

        else:
            # Unknown state — reset and escalate generically
            session.metadata = {k: v for k, v in metadata.items() if not k.startswith("_escalation_")}
            session.status = "escalated"
            message = "I'll connect you with a human agent right away. Please hold."
            action = "phone_transfer"

        self.db.add(Message(
            session_id=session.id, tenant_id=session.tenant_id,
            role="user", content=user_message, tokens_used=0, latency_ms=0,
        ))
        self.db.add(Message(
            session_id=session.id, tenant_id=session.tenant_id,
            role="assistant", content=message, tokens_used=0, latency_ms=latency_ms,
        ))

        return ChatResponse(
            session_id=session.id,
            message=message,
            tool_calls_made=[],
            suggested_actions=[],
            escalate_to_human=action == "phone_callback_scheduled",
            escalation_action=action,
            latency_ms=latency_ms,
            tokens_used=0,
        )

    # ------------------------------------------------------------------
    # Connector fire-and-forget helper
    # ------------------------------------------------------------------

    async def _fire_connector(
        self,
        escalation_config: dict,
        agent: Agent,
        session: AgentSession,
        trigger_message: str,
        contact_name: str = "",
        contact_phone: str = "",
        contact_email: str = "",
    ) -> None:
        """
        Asynchronously trigger the configured live-agent connector with:
          1. Idempotency guard — Redis SET NX prevents duplicate escalations
          2. Persistent audit record — written BEFORE the background task fires
             so a crash doesn't lose the attempt
          3. Non-blocking — connector latency never delays the chat response
        """
        from app.models.agent import EscalationAttempt
        from app.connectors.factory import trigger_connector_with_idempotency

        connector_type = (escalation_config.get("connector_type") or "").lower().strip()

        # Fetch recent messages for the transcript (last 30 turns)
        try:
            result = await self.db.execute(
                select(Message)
                .where(Message.session_id == session.id)
                .order_by(Message.created_at.asc())
            )
            msgs = result.scalars().all()
            history = [{"role": m.role, "content": m.content} for m in msgs]
        except Exception:
            history = []

        payload = EscalationPayload(
            tenant_id=str(session.tenant_id),
            session_id=str(session.id),
            agent_name=agent.name or "AscenAI Bot",
            contact_name=contact_name,
            contact_phone=contact_phone,
            contact_email=contact_email,
            history=history,
            trigger_message=trigger_message,
            channel=session.channel or "web",
        )

        # Persist audit record BEFORE background task (DLQ pattern)
        attempt = EscalationAttempt(
            tenant_id=session.tenant_id,
            session_id=str(session.id),
            agent_name=agent.name or "AscenAI Bot",
            connector_type=connector_type,
            channel=session.channel or "web",
            contact_name=contact_name or None,
            contact_phone=contact_phone or None,
            contact_email=contact_email or None,
            trigger_message=trigger_message[:1000] if trigger_message else None,
            status="pending",
            payload_snapshot={
                "history_len": len(history),
                "trigger": trigger_message[:200] if trigger_message else "",
            },
        )
        try:
            self.db.add(attempt)
            await self.db.flush()
            attempt_id = str(attempt.id)
        except Exception as exc:
            logger.warning("escalation_attempt_persist_failed", error=str(exc))
            attempt_id = None

        async def _run_and_update():
            try:
                from app.core.database import AsyncSessionLocal
                result = await trigger_connector_with_idempotency(
                    escalation_config, payload, redis=self.redis
                )
                if attempt_id:
                    async with AsyncSessionLocal() as db2:
                        row = await db2.get(EscalationAttempt, attempt_id)
                        if row:
                            if result is None:
                                row.status = "skipped"
                            elif result.ticket_id == "deduplicated":
                                row.status = "deduplicated"
                            elif result.success:
                                row.status = "success"
                                row.ticket_id = result.ticket_id or None
                                row.conversation_url = result.conversation_url or None
                            else:
                                row.status = "failed"
                                row.error_message = result.error[:1000] if result.error else None
                            await db2.commit()
            except Exception as exc:
                logger.error("escalation_background_task_failed", attempt_id=attempt_id, error=str(exc))

        # Run in background so connector latency doesn't delay the response
        asyncio.create_task(_run_and_update())

    # ------------------------------------------------------------------
    # TC-E01: Emergency bypass
    # ------------------------------------------------------------------

    def _check_emergency(self, user_message: str, agent: Agent) -> Optional[str]:
        """
        Return a hardcoded life-safety response if the agent is in a health
        context and the user message contains emergency keywords (TC-E01).
        Runs BEFORE the LLM pipeline — latency ~0 ms.
        """
        business_type = (agent.business_type or "").lower().replace(" ", "_")
        if business_type not in _EMERGENCY_BUSINESS_TYPES:
            return None
        msg_lower = user_message.lower()
        for kw in _EMERGENCY_KEYWORDS:
            if kw in msg_lower:
                logger.warning(
                    "emergency_keyword_detected",
                    keyword=kw,
                    agent_id=str(agent.id),
                    business_type=business_type,
                )
                return _EMERGENCY_RESPONSE
        return None

    # ------------------------------------------------------------------
    # TC-D02: High-risk tool confirmation gate
    # ------------------------------------------------------------------

    def _requires_confirmation(
        self, tool_calls: list, user_message: str, history: list
    ) -> Optional[str]:
        """
        Return a confirmation prompt string if the LLM wants to call a
        high-risk tool but the user's most recent message is not an
        explicit confirmation (TC-D02).

        Returns None if no confirmation is required.
        """
        high_risk = [tc for tc in tool_calls if tc.name in _HIGH_RISK_TOOLS]
        if not high_risk:
            return None

        # Check if the user's current message (or immediately prior) is a confirm
        msg_lower = user_message.lower().strip().rstrip(".,!")
        if any(phrase in msg_lower for phrase in _CONFIRMATION_PHRASES):
            return None  # User has confirmed — proceed

        # Build a natural-language summary of what will happen
        tool_names = ", ".join(tc.name.replace("_", " ") for tc in high_risk)
        return (
            f"I'm about to {tool_names}. This action cannot be undone. "
            "Please reply 'confirm' to proceed or 'cancel' to abort."
        )

    # ------------------------------------------------------------------
    # TC-C01: Role/system injection sanitiser
    # ------------------------------------------------------------------

    @staticmethod
    def _sanitize_user_message(text: str) -> str:
        """
        Strip role-injection tokens from user input before passing to the LLM.
        Prevents prompt injection via [SYSTEM], <system>, <<SYS>>, etc. (TC-C01).
        """
        sanitized = _ROLE_INJECTION_PATTERN.sub("", text).strip()
        if sanitized != text:
            logger.warning("role_injection_stripped", original_len=len(text))
        return sanitized

    # ------------------------------------------------------------------
    # TC-B04/B05: Jailbreak / roleplay injection detection
    # ------------------------------------------------------------------

    def _check_jailbreak(self, user_message: str, agent: Agent) -> Optional[str]:
        """
        Return a canned refusal if the message is a clear jailbreak attempt (TC-B04/B05).
        Runs BEFORE the LLM — avoids spending tokens on adversarial prompts.
        """
        if _JAILBREAK_PATTERN.search(user_message):
            business_type = (agent.business_type or "our business").replace("_", " ").title()
            logger.warning(
                "jailbreak_attempt_detected",
                agent_id=str(agent.id),
                snippet=user_message[:80],
            )
            return (
                f"I'm only here to help with {business_type} services. "
                "How can I assist you today?"
            )
        return None

    # ------------------------------------------------------------------
    # TC-C03: Consecutive fallback counter
    # ------------------------------------------------------------------

    async def _increment_fallback_counter(self, session_id: str) -> int:
        """Increment the per-session fallback counter in Redis and return new value."""
        if self.redis is None:
            return 0
        key = f"{_FALLBACK_COUNTER_PREFIX}{session_id}"
        try:
            count = await self.redis.incr(key)
            await self.redis.expire(key, 3600)  # reset after 1 hour of inactivity
            return int(count)
        except Exception:
            return 0

    async def _reset_fallback_counter(self, session_id: str) -> None:
        """Reset the fallback counter after a successful (non-fallback) response."""
        if self.redis is None:
            return
        key = f"{_FALLBACK_COUNTER_PREFIX}{session_id}"
        try:
            await self.redis.delete(key)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Per-tenant daily token budget (prevents runaway LLM spend)
    # ------------------------------------------------------------------

    _DAILY_TOKEN_LIMIT = 2_000_000  # 2M tokens/day per tenant (~$0.40 Gemini Flash)

    async def _check_token_budget(self, tenant_id: str) -> bool:
        """Return True if tenant is within budget, False if exceeded."""
        if self.redis is None:
            return True  # fail-open when Redis unavailable
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        key = f"token_budget:{tenant_id}:{today}"
        try:
            used = await self.redis.get(key)
            return int(used or 0) < self._DAILY_TOKEN_LIMIT
        except Exception:
            return True  # fail-open

    async def _record_token_usage(self, tenant_id: str, tokens: int) -> None:
        """Increment daily token counter for the tenant."""
        if self.redis is None or tokens <= 0:
            return
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        key = f"token_budget:{tenant_id}:{today}"
        try:
            pipe = self.redis.pipeline()
            pipe.incrby(key, tokens)
            pipe.expire(key, 86400 * 2)  # keep for 2 days for debugging
            await pipe.execute()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # TC-D01: Tool call name validation
    # ------------------------------------------------------------------

    @staticmethod
    def _filter_unauthorized_tool_calls(
        tool_calls: list, enabled_tools: list[str]
    ) -> list:
        """
        Drop tool calls whose name is not in the agent's enabled tools list (TC-D01).
        Logs a warning for each dropped call.
        """
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

    # ------------------------------------------------------------------
    # TC-D03: Receipt summary after high-risk tool
    # ------------------------------------------------------------------

    @staticmethod
    def _build_receipt_summary(tool_calls_made: list[dict]) -> str:
        """
        Return a brief spoken receipt for completed high-risk tool calls (TC-D03).
        Only includes tools that actually executed (not confirmation-gated ones).
        """
        receipts = []
        for entry in tool_calls_made:
            tool = entry.get("tool", "")
            if tool not in _HIGH_RISK_TOOLS:
                continue
            result = entry.get("result", {})
            if isinstance(result, dict) and result.get("error"):
                continue  # Only receipt for successful calls
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

    # ------------------------------------------------------------------
    # TC-E02: Professional claim check (output side)
    # ------------------------------------------------------------------

    @staticmethod
    def _check_professional_claims(response: str) -> str:
        """
        Append a disclaimer if the response contains professional claim phrases (TC-E02).
        """
        lower = response.lower()
        for phrase in _PROFESSIONAL_CLAIM_PHRASES:
            if phrase in lower:
                return response + _PROFESSIONAL_DISCLAIMER
        return response

    # ------------------------------------------------------------------
    # TC-E05: Credential scrubber
    # ------------------------------------------------------------------

    @staticmethod
    def _scrub_credentials(text: str) -> str:
        """Replace API key / token patterns with [REDACTED] (TC-E05)."""
        return _CREDENTIAL_SCRUB_PATTERN.sub("[REDACTED]", text)

    # ------------------------------------------------------------------
    # TC-F02: LLM call with timeout
    # ------------------------------------------------------------------

    async def _llm_complete_with_timeout(self, **kwargs) -> LLMResponse:
        """
        Wrap self.llm.complete() with a hard timeout (TC-F02).
        Returns a graceful fallback LLMResponse on timeout.
        """
        try:
            return await asyncio.wait_for(
                self.llm.complete(**kwargs),
                timeout=LLM_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.error(
                "llm_timeout",
                timeout_s=LLM_TIMEOUT_SECONDS,
                model=getattr(self.llm, "model", "unknown"),
            )
            from app.services.llm_client import LLMResponse, TokenUsage
            return LLMResponse(
                content=(
                    "I'm sorry, I'm taking longer than expected to respond. "
                    "Please try again in a moment."
                ),
                tool_calls=None,
                finish_reason="timeout",
                usage=TokenUsage(),
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
