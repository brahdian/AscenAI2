import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import (
    String, Boolean, Text, ForeignKey, func, Index, DateTime, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class AgentVariable(Base):
    """
    Variables defined on an Agent.
    Can be 'global' (persists across the session) or 'local' (scoped to a playbook execution).
    """
    __tablename__ = "agent_variables"
    __table_args__ = (
        Index("ix_agent_variables_agent_id", "agent_id"),
        Index("ix_agent_variables_tenant_id", "tenant_id"),
        UniqueConstraint("agent_id", "name", name="ux_agent_variables_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    
    # Nullable playbook association for scope="local" variables
    playbook_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_playbooks.id", ondelete="CASCADE"), nullable=True
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # 'global' or 'local'
    scope: Mapped[str] = mapped_column(String(20), nullable=False, default="global")
    
    # 'string', 'number', 'boolean', 'object'
    data_type: Mapped[str] = mapped_column(String(20), nullable=False, default="string")

    default_value: Mapped[Optional[dict]] = mapped_column("default_value", JSONB, nullable=True)

    # When True the value is treated as a secret: redacted in API responses,
    # never logged. UI should render it as a password field.
    is_secret: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    agent: Mapped["Agent"] = relationship("Agent", back_populates="variables")

    def to_dict(self, *, redact_secrets: bool = True) -> dict:
        return {
            "id": str(self.id),
            "agent_id": str(self.agent_id),
            "tenant_id": str(self.tenant_id),
            "playbook_id": str(self.playbook_id) if self.playbook_id else None,
            "name": self.name,
            "description": self.description,
            "scope": self.scope,
            "data_type": self.data_type,
            # Redact the actual value for secret variables to prevent leakage
            "default_value": "***" if (self.is_secret and redact_secrets) else self.default_value,
            "is_secret": self.is_secret,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
