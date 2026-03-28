"""
TraceLogger — collects timing and artifacts throughout a single orchestrator request,
then persists a ConversationTrace row at the end of the turn.

Usage:
    tracer = TraceLogger(session_id, tenant_id, agent_id, turn_index)
    tracer.set_system_prompt(system_prompt, version_id)
    tracer.set_memory(short_term, summary, long_term)
    tracer.set_retrieved_chunks(context_items)
    tracer.set_messages_sent(messages)      # PII already pseudonymized at this point
    tracer.start_timer("llm")
    ... llm call ...
    tracer.stop_timer("llm")
    tracer.set_llm_response(raw_response, provider, model)
    tracer.add_tool_call(tool, args_redacted, result_redacted, latency_ms)
    tracer.set_guardrail_actions(actions)
    tracer.set_pii_entity_types(types)
    tracer.set_final_response(final_response)
    await tracer.persist(db)
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trace import ConversationTrace

logger = structlog.get_logger(__name__)

# Recognised latency phases
_VALID_PHASES = frozenset({"memory", "retrieval", "llm", "tools", "guardrails"})


class TraceLogger:
    """
    Collects timing and artifacts throughout a single orchestrator request,
    then persists to DB at the end of the turn via :meth:`persist`.
    """

    def __init__(
        self,
        session_id: str,
        tenant_id: uuid.UUID,
        agent_id: uuid.UUID,
        turn_index: int,
    ) -> None:
        self.session_id = session_id
        self.tenant_id = tenant_id
        self.agent_id = agent_id
        self.turn_index = turn_index

        # Context fields
        self._system_prompt: str = ""
        self._prompt_version_id: Optional[str] = None
        self._memory_snapshot: dict = {}
        self._retrieved_chunks: list = []
        self._grounding_used: bool = False
        self._messages_sent: list = []

        # LLM response
        self._llm_provider: str = ""
        self._llm_model: str = ""
        self._raw_llm_response: str = ""

        # Tool calls
        self._tool_calls: list[dict] = []

        # Guardrails
        self._guardrail_input_check: Optional[str] = None
        self._guardrail_actions: list = []
        self._pii_entity_types: list = []

        # Final
        self._final_response: str = ""
        self._message_id: Optional[uuid.UUID] = None

        # Timers: {phase: start_monotonic}
        self._timers: dict[str, float] = {}
        # Accumulated ms per phase
        self._latency_breakdown: dict[str, float] = {p: 0.0 for p in _VALID_PHASES}

    # ── Context setters ───────────────────────────────────────────────────────

    def set_system_prompt(self, content: str, version_id: Optional[str] = None) -> None:
        self._system_prompt = content or ""
        self._prompt_version_id = version_id

    def set_memory(
        self,
        short_term: list,
        summary: str,
        long_term: Any,
    ) -> None:
        self._memory_snapshot = {
            "short_term": short_term or [],
            "summary": summary or "",
            "long_term": long_term or {},
        }

    def set_retrieved_chunks(self, chunks: list) -> None:
        """
        Store retrieved RAG chunks.  Each chunk should be a dict with keys:
        content, score, document_id, title.
        """
        self._retrieved_chunks = chunks or []
        self._grounding_used = bool(chunks)

    def set_messages_sent(self, messages: list) -> None:
        """
        Store the full messages array sent to the LLM.
        PII must already be pseudonymized / redacted before calling this.
        """
        self._messages_sent = messages or []

    def set_message_id(self, message_id: uuid.UUID) -> None:
        """Link to the persisted assistant Message row (set after DB insert)."""
        self._message_id = message_id

    # ── Timing ───────────────────────────────────────────────────────────────

    def start_timer(self, phase: str) -> None:
        """Start wall-clock timer for *phase*.  Silently ignored for unknown phases."""
        if phase not in _VALID_PHASES:
            logger.warning("trace_unknown_phase", phase=phase)
            return
        self._timers[phase] = time.monotonic()

    def stop_timer(self, phase: str) -> None:
        """Stop timer for *phase* and accumulate elapsed milliseconds."""
        if phase not in _VALID_PHASES:
            return
        start = self._timers.pop(phase, None)
        if start is None:
            logger.warning("trace_stop_without_start", phase=phase)
            return
        elapsed_ms = (time.monotonic() - start) * 1000.0
        self._latency_breakdown[phase] = self._latency_breakdown.get(phase, 0.0) + elapsed_ms

    # ── LLM response ─────────────────────────────────────────────────────────

    def set_llm_response(self, raw: str, provider: str, model: str) -> None:
        self._raw_llm_response = raw or ""
        self._llm_provider = provider or ""
        self._llm_model = model or ""

    # ── Tool calls ───────────────────────────────────────────────────────────

    def add_tool_call(
        self,
        tool_name: str,
        args: Any,
        result: Any,
        latency_ms: float,
    ) -> None:
        """
        Append one tool-call record.
        *args* and *result* must already be redacted / safe to store.
        """
        self._tool_calls.append(
            {
                "tool": tool_name,
                "arguments_redacted": args,
                "result_redacted": result,
                "latency_ms": latency_ms,
            }
        )

    # ── Guardrails ───────────────────────────────────────────────────────────

    def set_guardrail_input_check(self, block_reason: Optional[str]) -> None:
        """Record the reason an input guardrail blocked / modified the request."""
        self._guardrail_input_check = block_reason

    def set_guardrail_actions(self, actions: list) -> None:
        """Record output guardrail actions applied (e.g. 'pii_redacted', 'truncated')."""
        self._guardrail_actions = actions or []

    def set_pii_entity_types(self, types: list) -> None:
        """Record *types* of PII detected — never the actual values."""
        self._pii_entity_types = types or []

    # ── Final response ────────────────────────────────────────────────────────

    def set_final_response(self, response: str) -> None:
        """Record the text that was ultimately delivered to the user."""
        self._final_response = response or ""

    # ── Persist ───────────────────────────────────────────────────────────────

    async def persist(self, db: AsyncSession, tokens_used: int = 0) -> ConversationTrace:
        """
        Build a :class:`~app.models.trace.ConversationTrace` from the collected
        data, add it to *db*, and flush (does NOT commit — caller owns the
        transaction boundary).

        Returns the newly-created ORM object.
        """
        # Stop any timers that were never explicitly stopped
        for phase in list(self._timers.keys()):
            logger.warning("trace_timer_not_stopped", phase=phase)
            self.stop_timer(phase)

        latency_breakdown = {
            f"{phase}_ms": round(ms, 2)
            for phase, ms in self._latency_breakdown.items()
        }

        trace = ConversationTrace(
            session_id=self.session_id,
            message_id=self._message_id,
            tenant_id=self.tenant_id,
            agent_id=self.agent_id,
            turn_index=self.turn_index,
            system_prompt=self._system_prompt,
            prompt_version_id=self._prompt_version_id,
            memory_snapshot=self._memory_snapshot,
            retrieved_chunks=self._retrieved_chunks,
            grounding_used=self._grounding_used,
            messages_sent=self._messages_sent,
            llm_provider=self._llm_provider,
            llm_model=self._llm_model,
            raw_llm_response=self._raw_llm_response,
            tool_calls=self._tool_calls,
            guardrail_input_check=self._guardrail_input_check,
            guardrail_actions=self._guardrail_actions,
            pii_entity_types=self._pii_entity_types,
            final_response=self._final_response,
            latency_breakdown=latency_breakdown,
            tokens_used=tokens_used,
        )

        db.add(trace)
        try:
            await db.flush()
        except Exception as exc:
            logger.error(
                "trace_persist_failed",
                session_id=self.session_id,
                turn_index=self.turn_index,
                error=str(exc),
            )
            raise

        logger.debug(
            "trace_persisted",
            session_id=self.session_id,
            turn_index=self.turn_index,
            trace_id=str(trace.id),
        )
        return trace
