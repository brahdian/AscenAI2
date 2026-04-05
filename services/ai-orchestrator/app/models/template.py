import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import (
    String, Boolean, Text, Integer, ForeignKey, func, Index, DateTime
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class AgentTemplate(Base):
    __tablename__ = "agent_templates"
    __table_args__ = (
        Index("ix_agent_templates_key", "key", unique=True),
        Index("ix_agent_templates_category", "category"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    versions: Mapped[list["TemplateVersion"]] = relationship(
        "TemplateVersion", back_populates="template", cascade="all, delete-orphan"
    )
    variables: Mapped[list["TemplateVariable"]] = relationship(
        "TemplateVariable", back_populates="template", cascade="all, delete-orphan"
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "key": self.key,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class TemplateVersion(Base):
    __tablename__ = "template_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_templates.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    system_prompt_template: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    orchestration_logic: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    template: Mapped["AgentTemplate"] = relationship("AgentTemplate", back_populates="versions")
    playbooks: Mapped[list["TemplatePlaybook"]] = relationship(
        "TemplatePlaybook", back_populates="version", cascade="all, delete-orphan"
    )
    tools: Mapped[list["TemplateTool"]] = relationship(
        "TemplateTool", back_populates="version", cascade="all, delete-orphan"
    )
    instances: Mapped[list["AgentTemplateInstance"]] = relationship(
        "AgentTemplateInstance", back_populates="version", cascade="all, delete-orphan"
    )


class TemplateVariable(Base):
    __tablename__ = "template_variables"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_templates.id"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    default_value: Mapped[Optional[dict]] = mapped_column("default_value", JSONB, nullable=True)
    validation_rules: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    is_required: Mapped[bool] = mapped_column(Boolean, default=False)

    template: Mapped["AgentTemplate"] = relationship("AgentTemplate", back_populates="variables")


class TemplatePlaybook(Base):
    __tablename__ = "template_playbooks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    template_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("template_versions.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    trigger_condition: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    flow_definition: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    version: Mapped["TemplateVersion"] = relationship("TemplateVersion", back_populates="playbooks")


class TemplateTool(Base):
    __tablename__ = "template_tools"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    template_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("template_versions.id"), nullable=False
    )
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    required_config_schema: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    version: Mapped["TemplateVersion"] = relationship("TemplateVersion", back_populates="tools")


class AgentTemplateInstance(Base):
    __tablename__ = "agent_template_instances"
    __table_args__ = (
        Index("ix_template_instances_tenant_id", "tenant_id"),
        Index("ix_template_instances_agent_id", "agent_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=True
    )
    template_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("template_versions.id"), nullable=False
    )
    variable_values: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    tool_configs: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    version: Mapped["TemplateVersion"] = relationship("TemplateVersion", back_populates="instances")
