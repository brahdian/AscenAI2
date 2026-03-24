import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class Tool(Base):
    __tablename__ = "mcp_tools"
    __table_args__ = (
        Index("ix_mcp_tools_tenant_id", "tenant_id"),
        Index("ix_mcp_tools_tenant_name", "tenant_id", "name", unique=True),
        Index("ix_mcp_tools_category", "category"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[str] = mapped_column(
        String(100), nullable=False, default="general"
    )

    # JSON Schemas for input/output validation
    input_schema: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    output_schema: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # HTTP tool configuration
    endpoint_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    auth_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # auth_config shape: {"type": "api_key|oauth|bearer|none", "header": "...", "value_encrypted": "..."}

    # Rate limiting & timeout
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=30)

    # Flags
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Arbitrary metadata
    tool_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
    )

    # Relationships
    executions: Mapped[list["ToolExecution"]] = relationship(
        "ToolExecution", back_populates="tool", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Tool name={self.name} tenant={self.tenant_id}>"


class ToolExecution(Base):
    __tablename__ = "mcp_tool_executions"
    __table_args__ = (
        Index("ix_mcp_tool_executions_tenant_id", "tenant_id"),
        Index("ix_mcp_tool_executions_tool_id", "tool_id"),
        Index("ix_mcp_tool_executions_session_id", "session_id"),
        Index("ix_mcp_tool_executions_status", "status"),
        Index("ix_mcp_tool_executions_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    tool_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mcp_tools.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    trace_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    input_data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    output_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Status: pending | running | completed | failed | timeout
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timing
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationship
    tool: Mapped["Tool"] = relationship("Tool", back_populates="executions")

    def __repr__(self) -> str:
        return f"<ToolExecution id={self.id} status={self.status}>"
