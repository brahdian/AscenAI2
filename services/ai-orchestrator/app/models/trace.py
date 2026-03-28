"""
ConversationTrace model — full artifact log for every LLM call.
Enables conversation replay, debugging, and "why did the agent say this?" analysis.
Stored separately from messages to avoid bloating the messages table.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func, Index, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ConversationTrace(Base):
    """
    Full artifact log for every LLM call.  Enables conversation replay and debugging.
    Stored separately from messages to avoid bloating the messages table.
    """

    __tablename__ = "conversation_traces"
    __table_args__ = (
        # Fast replay queries: all turns for a session in order
        Index("ix_traces_session_turn", "session_id", "turn_index"),
        # Tenant-scoped time-range queries (analytics, audit)
        Index("ix_traces_tenant_created", "tenant_id", "created_at"),
        # Lookup by agent for cross-session analysis
        Index("ix_traces_agent_id", "agent_id"),
    )

    # ── Identity ──────────────────────────────────────────────────────────────
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Null for intermediate tool-call steps that don't map to a persisted message
    message_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    # 0-based turn counter within the session
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # ── Full context sent to LLM ──────────────────────────────────────────────
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Which prompt version was active when this call was made
    prompt_version_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # {short_term: [...], summary: "...", long_term: {...}}
    memory_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # list of {content, score, document_id, title}
    retrieved_chunks: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    grounding_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Full messages array sent to the LLM (PII already pseudonymized at this point)
    messages_sent: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # ── LLM response ─────────────────────────────────────────────────────────
    llm_provider: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    llm_model: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    # Raw text from the LLM before guardrail post-processing
    raw_llm_response: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # ── Tool calls ───────────────────────────────────────────────────────────
    # [{tool, arguments_redacted, result_redacted, latency_ms}]
    tool_calls: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # ── Guardrails ───────────────────────────────────────────────────────────
    # Non-null when an input guardrail fired and blocked/modified the request
    guardrail_input_check: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # List of output guardrail actions applied (e.g. "pii_redacted", "truncated")
    guardrail_actions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # PII entity types detected — deliberately NOT storing the actual values
    pii_entity_types: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # ── Final ────────────────────────────────────────────────────────────────
    # The text that was ultimately delivered to the user
    final_response: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # {memory_ms, retrieval_ms, llm_ms, tools_ms, guardrails_ms}
    latency_breakdown: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    tokens_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # ── Helpers ───────────────────────────────────────────────────────────────
    def to_summary_dict(self) -> dict:
        """Lightweight summary suitable for the replay list endpoint."""
        # Extract the user message from messages_sent (last user role entry)
        user_message = ""
        for msg in reversed(self.messages_sent or []):
            if isinstance(msg, dict) and msg.get("role") == "user":
                content = msg.get("content", "")
                user_message = content if isinstance(content, str) else str(content)
                break

        return {
            "turn_index": self.turn_index,
            "user_message": user_message,
            "system_prompt_excerpt": (self.system_prompt or "")[:300],
            "memory_summary": (self.memory_snapshot or {}).get("summary", ""),
            "retrieved_chunks_count": len(self.retrieved_chunks or []),
            "tool_calls": self.tool_calls or [],
            "guardrail_actions": self.guardrail_actions or [],
            "final_response": self.final_response,
            "latency_breakdown": self.latency_breakdown or {},
            "tokens_used": self.tokens_used,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def to_full_dict(self) -> dict:
        """Complete detail dict for the per-turn detail endpoint."""
        return {
            "id": str(self.id),
            "session_id": self.session_id,
            "message_id": str(self.message_id) if self.message_id else None,
            "tenant_id": str(self.tenant_id),
            "agent_id": str(self.agent_id),
            "turn_index": self.turn_index,
            "system_prompt": self.system_prompt,
            "prompt_version_id": self.prompt_version_id,
            "memory_snapshot": self.memory_snapshot or {},
            "retrieved_chunks": self.retrieved_chunks or [],
            "grounding_used": self.grounding_used,
            "messages_sent": self.messages_sent or [],
            "llm_provider": self.llm_provider,
            "llm_model": self.llm_model,
            "raw_llm_response": self.raw_llm_response,
            "tool_calls": self.tool_calls or [],
            "guardrail_input_check": self.guardrail_input_check,
            "guardrail_actions": self.guardrail_actions or [],
            "pii_entity_types": self.pii_entity_types or [],
            "final_response": self.final_response,
            "latency_breakdown": self.latency_breakdown or {},
            "tokens_used": self.tokens_used,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
