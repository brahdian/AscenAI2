import uuid
from datetime import datetime, date
from typing import Optional
from sqlalchemy import (
    String, Boolean, Text, Integer, Float, Date,
    DateTime, ForeignKey, func, Index
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

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
    # Greeting sent at the start of every new session (text + optional pre-recorded audio)
    greeting_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    voice_greeting_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    tools: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True, default=list)
    knowledge_base_ids: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True, default=list
    )
    llm_config: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True, default=dict)
    escalation_config: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True, default=dict
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
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
            "greeting_message": self.greeting_message,
            "voice_greeting_url": self.voice_greeting_url,
            "tools": self.tools or [],
            "knowledge_base_ids": self.knowledge_base_ids or [],
            "llm_config": self.llm_config or {},
            "escalation_config": self.escalation_config or {},
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        Index("ix_sessions_tenant_id", "tenant_id"),
        Index("ix_sessions_agent_id", "agent_id"),
        Index("ix_sessions_customer", "tenant_id", "customer_identifier"),
        Index("ix_sessions_status", "tenant_id", "status"),
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
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    agent: Mapped["Agent"] = relationship("Agent", back_populates="sessions")
    messages: Mapped[list["Message"]] = relationship(
        "Message", back_populates="session", order_by="Message.created_at"
    )

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

    # Greeting: sent as the first assistant message in a new session
    greeting_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

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
            "greeting_message": self.greeting_message,
            "instructions": self.instructions,
            "tone": self.tone,
            "dos": self.dos or [],
            "donts": self.donts or [],
            "scenarios": self.scenarios or [],
            "out_of_scope_response": self.out_of_scope_response,
            "fallback_response": self.fallback_response,
            "custom_escalation_message": self.custom_escalation_message,
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
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    vector_ids: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True, default=list)
    status: Mapped[str] = mapped_column(String(20), default="processing")  # processing | ready | failed
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    agent: Mapped["Agent"] = relationship("Agent", back_populates="documents")

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
            "max_response_length": self.max_response_length,
            "require_disclaimer": self.require_disclaimer,
            "blocked_message": self.blocked_message,
            "off_topic_message": self.off_topic_message,
            "content_filter_level": self.content_filter_level,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


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
