import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import (
    String, Boolean, Text, ForeignKey, func, Index, DateTime
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class AgentTool(Base):
    """
    Explicit tool definition attached to an Agent.
    Allows defining input schemas, output schemas, and configuration.
    """
    __tablename__ = "agent_tools"
    __table_args__ = (
        Index("ix_agent_tools_agent_id", "agent_id"),
        Index("ix_agent_tools_tenant_id", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Built-in or custom connector (e.g. "shopify_search_products", "rest_api")
    connector_type: Mapped[str] = mapped_column(String(100), nullable=False, default="custom")
    
    # JSON Schema defining expected inputs from the playbook
    input_schema: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    
    # JSON Schema defining expected output structure
    output_schema: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    
    # Tool's specific configuration (e.g. base_url, headers template, standard param mapping)
    config: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    
    # True if the tool should bypass the LLM and return raw output directly to the user/UI
    is_raw_return: Mapped[bool] = mapped_column(Boolean, default=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    agent: Mapped["Agent"] = relationship("Agent", back_populates="tools_rel")

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "agent_id": str(self.agent_id),
            "tenant_id": str(self.tenant_id),
            "name": self.name,
            "description": self.description,
            "connector_type": self.connector_type,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "config": self.config,
            "is_raw_return": self.is_raw_return,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
