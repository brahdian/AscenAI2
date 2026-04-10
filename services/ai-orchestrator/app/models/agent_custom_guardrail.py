import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import Column, String, Boolean, ForeignKey, Text, DateTime, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base

class AgentCustomGuardrail(Base):
    """
    Agent-specific custom safety / tone / persona rules injected into system prompt.
    These are granular rules like "Never mention price for competitors".
    Separated from standard guardrails for memory efficiency.
    """
    __tablename__ = "agent_custom_guardrails"
    __table_args__ = (
        Index("ix_custom_guardrails_agent_id", "agent_id"),
        Index("ix_custom_guardrails_tenant_id", "tenant_id"),
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

    rule: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="Custom")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
