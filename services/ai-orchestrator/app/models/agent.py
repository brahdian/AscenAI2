import uuid
from datetime import datetime, date, timedelta, timezone
from typing import Optional
from sqlalchemy import (
    String, Boolean, Text, Integer, Float, Date,
    DateTime, ForeignKey, func, Index
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.ext.mutable import MutableDict, MutableList
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
        Index("ix_agents_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    business_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="generic"
    )
    personality: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    system_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    agent_config: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSONB), nullable=False, server_default='{}')

    voice_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    voice_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    language: Mapped[str] = mapped_column(String(10), default="en")

    extension_number: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)
    is_available_as_tool: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Lifecycle state machine — mirrors is_active but carries richer semantics.
    # Values: draft | pending_payment | active | grace | expired | archived
    # Use app.services.agent_lifecycle.transition_agent() to change this field;
    # never mutate it directly outside of that service.
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="DRAFT")
    stripe_subscription_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Agent subscription expiry - set when payment is made, checked before allowing agent usage
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    grace_period_ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
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
            "agent_config": self.agent_config or {},
            "voice_enabled": self.voice_enabled,
            "voice_id": self.voice_id,
            "language": self.language,
            "extension_number": self.extension_number,
            "is_available_as_tool": self.is_available_as_tool,
            "status": self.status,
            "stripe_subscription_id": self.stripe_subscription_id,
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
        "metadata", MutableDict.as_mutable(JSONB), nullable=True, default=dict
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
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)

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
            "ip_address": self.ip_address,
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
    tool_calls: Mapped[Optional[dict]] = mapped_column(MutableDict.as_mutable(JSONB), nullable=True)
    tool_results: Mapped[Optional[dict]] = mapped_column(MutableDict.as_mutable(JSONB), nullable=True)
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
    labels: Mapped[Optional[list]] = mapped_column(MutableList.as_mutable(JSONB), nullable=True, default=list)
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
    playbook_correction: Mapped[Optional[dict]] = mapped_column(MutableDict.as_mutable(JSONB), nullable=True)
    # Tool-call corrections: list of {tool_name, was_correct, correct_tool, reason}
    # Set per-tool when the operator marks incorrect tool calls
    tool_corrections: Mapped[Optional[list]] = mapped_column(MutableList.as_mutable(JSONB), nullable=True)

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
    intent_triggers: Mapped[Optional[list]] = mapped_column(MutableList.as_mutable(JSONB), nullable=True, default=list)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)

    config: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSONB), nullable=False, server_default='{}')

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_from_template: Mapped[bool] = mapped_column(Boolean, default=False)
    source_template_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)

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
            "config": self.config or {},
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


from sqlalchemy import UniqueConstraint

class AgentDocument(Base):
    __tablename__ = "agent_documents"
    __table_args__ = (
        Index("ix_agent_docs_agent_id", "agent_id"),
        Index("ix_agent_docs_tenant_id", "tenant_id"),
        UniqueConstraint("agent_id", "name", name="uq_agent_doc_name"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str] = mapped_column(String(50), nullable=False)  # pdf, txt, docx, md
    file_size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=True) # Now optional because it can be raw text
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True) # Direct raw text content
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True) # SHA-256 hash for deduplication

    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    embedding: Mapped[Optional[list[float]]] = mapped_column(Vector(768), nullable=True)
    vector_ids: Mapped[Optional[list]] = mapped_column(MutableList.as_mutable(JSONB), nullable=True, default=list)
    status: Mapped[str] = mapped_column(String(20), default="processing")  # draft | published | processing | ready | failed
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extraction_metadata: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True, default=dict) # Quality metrics (Phase 5)
    residency_region: Mapped[Optional[str]] = mapped_column(String(50), nullable=True) # Data residency (e.g. 'us', 'eu')
    valid_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True) # Fact staleness

    # Zenith Pillar 1: Forensic Traceability
    created_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True) # actor_email
    updated_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    trace_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    original_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    justification_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
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
            # No storage_path in to_dict (Phase 8 - Gap 1: Information Disclosure Fix)
            "content": self.content,
            "chunk_count": self.chunk_count,
            "status": self.status,
            "error_message": self.error_message,
            "extraction_metadata": self.extraction_metadata,
            "residency_region": self.residency_region,
            "valid_until": self.valid_until.isoformat() if self.valid_until else None,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "trace_id": self.trace_id,
            "original_ip": pii_service.redact(self.original_ip) if self.original_ip else None,
            "justification_id": self.justification_id,
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
    
    # Zenith Pillar 1: Granular Forensic Correlation
    trace_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)

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
    variables: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSONB), nullable=False, default=dict)
    history: Mapped[list] = mapped_column(MutableList.as_mutable(JSONB), nullable=False, default=list)
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

    # Consolidate all toggles, messages, levels into a single config blob
    config: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSONB), nullable=False, server_default='{}')

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
            "config": self.config or {},
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
    payload_snapshot: Mapped[Optional[dict]] = mapped_column(MutableDict.as_mutable(JSONB), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AgentGuardrailChangeRequest(Base):
    """
    Tracks requests to change global or system-wide guardrail rules.
    """
    __tablename__ = "guardrail_change_requests"
    __table_args__ = (
        Index("ix_gr_change_req_tenant_id", "tenant_id"),
        Index("ix_gr_change_req_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    guardrail_id: Mapped[str] = mapped_column(String(255), nullable=False)
    proposed_rule: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")  # pending, approved, rejected
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "guardrail_id": self.guardrail_id,
            "proposed_rule": self.proposed_rule,
            "reason": self.reason,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class GuardrailEvent(Base):
    """
    Audit log of when guardrails trigger (blocks, jailbreaks, emergencies, etc).
    """
    __tablename__ = "guardrail_events"
    __table_args__ = (
        Index("ix_gr_event_tenant_id", "tenant_id"),
        Index("ix_gr_event_agent_id", "agent_id"),
        Index("ix_gr_event_session_id", "session_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    session_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False) # e.g., 'input_blocked', 'emergency', 'jailbreak', 'pii_redacted'
    details: Mapped[Optional[dict]] = mapped_column(MutableDict.as_mutable(JSONB), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "agent_id": str(self.agent_id),
            "session_id": self.session_id,
            "event_type": self.event_type,
            "details": self.details or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
