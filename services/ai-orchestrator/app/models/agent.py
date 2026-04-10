import uuid
from datetime import datetime, date, timedelta, timezone
from typing import Optional
from sqlalchemy import (
    String, Boolean, Text, Integer, Float, Date,
    DateTime, ForeignKey, func, Index
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from pgvector.sqlalchemy import Vector
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.tool import AgentTool
    from app.models.variable import AgentVariable

from app.core.database import Base


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (
        Index("ix_agents_tenant_id", "tenant_id"),
        Index("ix_agents_tenant_active", "tenant_id", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    business_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="generic"
    )  # "pizza_shop", "clinic", "salon", "generic"
    personality: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    system_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    voice_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    voice_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    language: Mapped[str] = mapped_column(String(10), default="en")
    auto_detect_language: Mapped[bool] = mapped_column(Boolean, default=False)
    supported_languages: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True, default=list)
    # Greeting sent at the start of every new session (text + optional pre-recorded audio)
    greeting_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    voice_greeting_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    voice_system_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    voice_config: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True, default=dict
    )
    tools: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True, default=list)
    knowledge_base_ids: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True, default=list
    )
    llm_config: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True, default=dict)
    escalation_config: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True, default=dict
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Lifecycle state machine — mirrors is_active but carries richer semantics.
    # Values: draft | pending_payment | active | grace | expired | archived
    # Use app.services.agent_lifecycle.transition_agent() to change this field;
    # never mutate it directly outside of that service.
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    stripe_subscription_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    sessions: Mapped[list["Session"]] = relationship("Session", back_populates="agent")
    analytics: Mapped[list["AgentAnalytics"]] = relationship(
        "AgentAnalytics", back_populates="agent"
    )
    playbooks: Mapped[list["AgentPlaybook"]] = relationship(
        "AgentPlaybook", back_populates="agent", cascade="all, delete-orphan"
    )
    guardrails: Mapped[Optional["AgentGuardrails"]] = relationship(
        "AgentGuardrails", back_populates="agent", uselist=False, cascade="all, delete-orphan"
    )
    documents: Mapped[list["AgentDocument"]] = relationship(
        "AgentDocument", back_populates="agent", cascade="all, delete-orphan"
    )
    tools_rel: Mapped[list["AgentTool"]] = relationship(
        "AgentTool", back_populates="agent", cascade="all, delete-orphan"
    )
    variables: Mapped[list["AgentVariable"]] = relationship(
        "AgentVariable", back_populates="agent", cascade="all, delete-orphan"
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "name": self.name,
            "description": self.description,
            "business_type": self.business_type,
            "personality": self.personality,
            "system_prompt": self.system_prompt,
            "voice_enabled": self.voice_enabled,
            "voice_id": self.voice_id,
            "language": self.language,
            "auto_detect_language": self.auto_detect_language,
            "supported_languages": self.supported_languages or [],
            "greeting_message": self.greeting_message,
            "voice_greeting_url": self.voice_greeting_url,
            "voice_system_prompt": self.voice_system_prompt,
            "voice_config": self.voice_config or {},
            "tools": self.tools or [],
            "knowledge_base_ids": self.knowledge_base_ids or [],
            "llm_config": self.llm_config or {},
            "escalation_config": self.escalation_config or {},
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class AgentLifecycleAudit(Base):
    """Immutable audit trail of every agent lifecycle state transition."""

    __tablename__ = "agent_lifecycle_audit"
    __table_args__ = (
        Index("ix_alc_audit_agent_id", "agent_id"),
        Index("ix_alc_audit_tenant_id", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    from_state: Mapped[str] = mapped_column(String(30), nullable=False)
    to_state: Mapped[str] = mapped_column(String(30), nullable=False)
    actor_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    request_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        Index("ix_sessions_tenant_id", "tenant_id"),
        Index("ix_sessions_agent_id", "agent_id"),
        Index("ix_sessions_customer", "tenant_id", "customer_identifier"),
        Index("ix_sessions_status", "tenant_id", "status"),
        Index("ix_sessions_last_activity", "last_activity_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False
    )
    customer_identifier: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    channel: Mapped[str] = mapped_column(String(20), default="text")
    status: Mapped[str] = mapped_column(String(20), default="active")
    metadata_: Mapped[Optional[dict]] = mapped_column(
        "metadata", JSONB, nullable=True, default=dict
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_activity_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    turn_count: Mapped[int] = mapped_column(Integer, default=0)

    agent: Mapped["Agent"] = relationship("Agent", back_populates="sessions")
    messages: Mapped[list["Message"]] = relationship(
        "Message", back_populates="session", order_by="Message.created_at"
    )

    def is_expired(self, expiry_minutes: int = 30) -> bool:
        """Check if the session has expired due to inactivity."""
        if self.status in ("closed", "ended", "escalated"):
            return True
        ref_time = self.last_activity_at or self.updated_at or self.started_at
        if ref_time is None:
            return False
        if ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - ref_time > timedelta(minutes=expiry_minutes)

    def touch(self) -> None:
        """Update last_activity_at to now, extending the session expiry."""
        self.last_activity_at = datetime.now(timezone.utc)

    def close(self) -> None:
        """Mark the session as closed."""
        self.status = "closed"
        self.ended_at = datetime.now(timezone.utc)

    def minutes_until_expiry(self, expiry_minutes: int = 30) -> float:
        """Return minutes remaining before session expires."""
        ref_time = self.last_activity_at or self.updated_at or self.started_at
        if ref_time is None:
            return float(expiry_minutes)
        if ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(timezone.utc) - ref_time).total_seconds() / 60.0
        return max(0.0, expiry_minutes - elapsed)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": str(self.tenant_id),
            "agent_id": str(self.agent_id),
            "customer_identifier": self.customer_identifier,
            "channel": self.channel,
            "status": self.status,
            "metadata": self.metadata_ or {},
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "last_activity_at": self.last_activity_at.isoformat() if self.last_activity_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_session_id", "session_id"),
        Index("ix_messages_tenant_id", "tenant_id"),
        Index("ix_messages_created_at", "session_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id"), nullable=False
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tool_calls: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    tool_results: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    is_fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    guardrail_triggered: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    playbook_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    sources: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    session: Mapped["Session"] = relationship("Session", back_populates="messages")

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "session_id": self.session_id,
            "tenant_id": str(self.tenant_id),
            "role": self.role,
            "content": self.content,
            "tool_calls": self.tool_calls,
            "tool_results": self.tool_results,
            "tokens_used": self.tokens_used,
            "latency_ms": self.latency_ms,
            "playbook_name": self.playbook_name,
            "sources": self.sources,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AgentAnalytics(Base):
    __tablename__ = "agent_analytics"
    __table_args__ = (
        Index("ix_analytics_tenant_agent", "tenant_id", "agent_id"),
        Index("ix_analytics_date", "tenant_id", "date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    total_sessions: Mapped[int] = mapped_column(Integer, default=0)
    total_messages: Mapped[int] = mapped_column(Integer, default=0)
    avg_response_latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    total_tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    tool_executions: Mapped[int] = mapped_column(Integer, default=0)
    escalations: Mapped[int] = mapped_column(Integer, default=0)
    successful_completions: Mapped[int] = mapped_column(Integer, default=0)
    total_chat_units: Mapped[int] = mapped_column(Integer, default=0)
    total_voice_minutes: Mapped[float] = mapped_column(Float, default=0.0)

    agent: Mapped["Agent"] = relationship("Agent", back_populates="analytics")

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "agent_id": str(self.agent_id),
            "date": self.date.isoformat() if self.date else None,
            "total_sessions": self.total_sessions,
            "total_messages": self.total_messages,
            "avg_response_latency_ms": self.avg_response_latency_ms,
            "total_tokens_used": self.total_tokens_used,
            "estimated_cost_usd": self.estimated_cost_usd,
            "tool_executions": self.tool_executions,
            "escalations": self.escalations,
            "successful_completions": self.successful_completions,
            "total_chat_units": self.total_chat_units,
            "total_voice_minutes": self.total_voice_minutes,
        }


class MessageFeedback(Base):
    __tablename__ = "message_feedback"
    __table_args__ = (
        Index("ix_feedback_tenant_id", "tenant_id"),
        Index("ix_feedback_message_id", "message_id"),
        Index("ix_feedback_agent_id", "agent_id"),
        Index("ix_feedback_rating", "tenant_id", "rating"),
        Index("ix_feedback_created_at", "tenant_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    # "positive" | "negative"
    rating: Mapped[str] = mapped_column(String(20), nullable=False)
    # e.g. ["helpful", "accurate"] or ["wrong", "off-topic", "inappropriate"]
    labels: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True, default=list)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # "user" (end-user) | "operator" (dashboard reviewer)
    feedback_source: Mapped[str] = mapped_column(String(20), nullable=False, default="user")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Operator's corrected / ideal response — used to generate few-shot examples
    ideal_response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Short explanation of why the original response was wrong
    correction_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Playbook correction: {"correct_playbook_id": str, "correct_playbook_name": str}
    # Set when the operator identifies a wrong playbook was triggered
    playbook_correction: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    # Tool-call corrections: list of {tool_name, was_correct, correct_tool, reason}
    # Set per-tool when the operator marks incorrect tool calls
    tool_corrections: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "message_id": str(self.message_id),
            "session_id": self.session_id,
            "tenant_id": str(self.tenant_id),
            "agent_id": str(self.agent_id),
            "rating": self.rating,
            "labels": self.labels or [],
            "comment": self.comment,
            "ideal_response": self.ideal_response,
            "correction_reason": self.correction_reason,
            "playbook_correction": self.playbook_correction,
            "tool_corrections": self.tool_corrections or [],
            "feedback_source": self.feedback_source,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AgentPlaybook(Base):
    """
    Operator-authored configuration that shapes how an agent behaves in chat.
    Injected into the system prompt on every turn.
    """
    __tablename__ = "agent_playbooks"
    __table_args__ = (
        Index("ix_playbooks_agent_id", "agent_id"),
        Index("ix_playbooks_tenant_id", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    name: Mapped[str] = mapped_column(String(255), nullable=False, default="Default")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    intent_triggers: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True, default=list)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)

    # NOTE: greeting_message has been moved to Agent level (Agent.greeting_message
    # + Agent.voice_greeting_url). This field is retained in DB for backward
    # compatibility but is no longer read by the orchestrator.

    # Detailed operator instructions injected into the system prompt
    instructions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Tone style: "professional" | "friendly" | "casual" | "empathetic"
    tone: Mapped[str] = mapped_column(String(50), nullable=False, default="professional")

    # Things to always do / never do  (JSONB list[str])
    dos: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True, default=list)
    donts: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True, default=list)

    # Scenario playbook: list of {trigger: str, response: str}
    scenarios: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True, default=list)

    # Canned fallback responses
    out_of_scope_response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    fallback_response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    custom_escalation_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Expected inputs to this playbook and data it outputs (for explicit variable passing)
    input_schema: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    output_schema: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # Playbook-specific tools injected ONLY when this playbook is active (List[str] names)
    tools: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True, default=list)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    agent: Mapped["Agent"] = relationship("Agent", back_populates="playbooks")

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "agent_id": str(self.agent_id),
            "tenant_id": str(self.tenant_id),
            "name": self.name,
            "description": self.description,
            "intent_triggers": self.intent_triggers or [],
            "is_default": self.is_default,

            "instructions": self.instructions,
            "tone": self.tone,
            "dos": self.dos or [],
            "donts": self.donts or [],
            "scenarios": self.scenarios or [],
            "out_of_scope_response": self.out_of_scope_response,
            "fallback_response": self.fallback_response,
            "custom_escalation_message": self.custom_escalation_message,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class AgentDocument(Base):
    __tablename__ = "agent_documents"
    __table_args__ = (
        Index("ix_agent_docs_agent_id", "agent_id"),
        Index("ix_agent_docs_tenant_id", "tenant_id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str] = mapped_column(String(50), nullable=False)  # pdf, txt, docx, md
    file_size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=True) # Now optional because it can be raw text
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True) # Direct raw text content

    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    embedding: Mapped[Optional[list[float]]] = mapped_column(Vector(768), nullable=True)
    vector_ids: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True, default=list)
    status: Mapped[str] = mapped_column(String(20), default="processing")  # draft | published | processing | ready | failed
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    agent: Mapped["Agent"] = relationship("Agent", back_populates="documents")
    chunks: Mapped[list["AgentDocumentChunk"]] = relationship(
        "AgentDocumentChunk", back_populates="document", cascade="all, delete-orphan"
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "agent_id": str(self.agent_id),
            "tenant_id": str(self.tenant_id),
            "name": self.name,
            "file_type": self.file_type,
            "file_size_bytes": self.file_size_bytes,
            "chunk_count": self.chunk_count,
            "status": self.status,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class AgentDocumentChunk(Base):
    __tablename__ = "agent_document_chunks"
    __table_args__ = (
        Index("ix_agent_doc_chunks_doc_id", "doc_id"),
        Index("ix_agent_doc_chunks_tenant_id", "tenant_id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doc_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agent_documents.id", ondelete="CASCADE"), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(768), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)

    document: Mapped["AgentDocument"] = relationship("AgentDocument", back_populates="chunks")


class PlaybookExecution(Base):
    """
    Durable checkpoint for a PlaybookEngine state machine execution.
    One row per (session_id, playbook_id) pair.
    Updated on every step transition.
    """
    __tablename__ = "playbook_executions"
    __table_args__ = (
        Index("ix_pb_exec_session", "session_id"),
        Index("ix_pb_exec_tenant_agent", "tenant_id", "agent_id"),
        Index("ix_pb_exec_status", "tenant_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    playbook_id: Mapped[str] = mapped_column(String(255), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    current_step_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    variables: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    history: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    step_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentGuardrails(Base):
    """
    Per-agent content policy: keyword blocks, topic restrictions,
    PII redaction, profanity filter, response length cap.
    """
    __tablename__ = "agent_guardrails"
    __table_args__ = (
        Index("ix_guardrails_agent_id", "agent_id"),
        Index("ix_guardrails_tenant_id", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    # Input checks
    blocked_keywords: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True, default=list)
    blocked_topics: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True, default=list)
    allowed_topics: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True, default=list)
    profanity_filter: Mapped[bool] = mapped_column(Boolean, default=True)

    # Output checks
    pii_redaction: Mapped[bool] = mapped_column(Boolean, default=False)
    # Reversible input pseudonymization — anonymize before LLM, restore in response
    pii_pseudonymization: Mapped[bool] = mapped_column(Boolean, default=True)
    max_response_length: Mapped[int] = mapped_column(Integer, default=0)  # 0 = unlimited
    require_disclaimer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Custom response messages
    blocked_message: Mapped[str] = mapped_column(
        Text, nullable=False, default="I'm sorry, I can't help with that."
    )
    off_topic_message: Mapped[str] = mapped_column(
        Text, nullable=False, default="I'm only able to help with topics related to our service."
    )

    # Display level (for UI)
    content_filter_level: Mapped[str] = mapped_column(
        String(20), nullable=False, default="medium"
    )  # none | low | medium | strict

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    agent: Mapped["Agent"] = relationship("Agent", back_populates="guardrails")

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "agent_id": str(self.agent_id),
            "tenant_id": str(self.tenant_id),
            "blocked_keywords": self.blocked_keywords or [],
            "blocked_topics": self.blocked_topics or [],
            "allowed_topics": self.allowed_topics or [],
            "profanity_filter": self.profanity_filter,
            "pii_redaction": self.pii_redaction,
            "pii_pseudonymization": self.pii_pseudonymization,
            "max_response_length": self.max_response_length,
            "require_disclaimer": self.require_disclaimer,
            "blocked_message": self.blocked_message,
            "off_topic_message": self.off_topic_message,
            "content_filter_level": self.content_filter_level,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# AgentFlow has been deprecated in favor of intent-driven Playbooks.


class EscalationAttempt(Base):
    """
    Persistent audit trail for every live-agent escalation attempt.

    Created BEFORE firing the connector (so we have a record even if the
    orchestrator crashes), then updated with the result.  This also serves as
    the dead-letter log — failed rows can be retried via a background job.
    """
    __tablename__ = "escalation_attempts"
    __table_args__ = (
        Index("ix_escalation_tenant_session", "tenant_id", "session_id"),
        Index("ix_escalation_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    session_id: Mapped[str] = mapped_column(String(255), nullable=False)
    agent_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    # Connector info
    connector_type: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    channel: Mapped[str] = mapped_column(String(20), nullable=False, default="web")

    # Contact info (stored encrypted in prod; plain for dev)
    contact_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    contact_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Escalation trigger
    trigger_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Result — updated after connector fires
    # status: "pending" | "success" | "failed" | "deduplicated"
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    ticket_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    conversation_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Full payload snapshot for replay
    payload_snapshot: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
