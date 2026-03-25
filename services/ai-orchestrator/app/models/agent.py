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
            "feedback_source": self.feedback_source,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
