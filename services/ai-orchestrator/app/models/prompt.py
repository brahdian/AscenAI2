"""
Prompt versioning and A/B testing ORM models.

Tables:
  prompt_versions  — immutable snapshots of an agent's system prompt
  prompt_ab_tests  — traffic-split experiments between two prompt versions
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, func, Index, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PromptVersion(Base):
    """
    Immutable snapshot of an agent's system prompt.

    Once created, the content of a version cannot be changed.
    To modify the prompt, create a new version.  At most one version
    per (agent_id, environment) can be ``is_active=True`` at a time.
    """

    __tablename__ = "prompt_versions"
    __table_args__ = (
        Index("ix_pv_agent_id", "agent_id"),
        Index("ix_pv_tenant_id", "tenant_id"),
        Index("ix_pv_agent_env_active", "agent_id", "environment", "is_active"),
        Index("ix_pv_version_number", "agent_id", "version_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )

    # Monotonically increasing version counter per agent
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # The immutable prompt content
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # environment: "all" | "dev" | "staging" | "production"
    environment: Mapped[str] = mapped_column(String(30), nullable=False, default="all")

    # Human notes for this version
    change_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Only one version per (agent, environment) can be active
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    activated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    deactivated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "agent_id": str(self.agent_id),
            "version_number": self.version_number,
            "content": self.content,
            "environment": self.environment,
            "change_notes": self.change_notes,
            "created_by": self.created_by,
            "is_active": self.is_active,
            "activated_at": self.activated_at.isoformat() if self.activated_at else None,
            "deactivated_at": self.deactivated_at.isoformat() if self.deactivated_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class PromptABTest(Base):
    """
    Traffic-split A/B test between two prompt versions.

    Routing: ``hash(session_id) % 100 < traffic_split_percent``
    → version_a is served;  otherwise → version_b is served.
    """

    __tablename__ = "prompt_ab_tests"
    __table_args__ = (
        Index("ix_ab_agent_id", "agent_id"),
        Index("ix_ab_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    version_a_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prompt_versions.id"), nullable=False
    )
    version_b_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prompt_versions.id"), nullable=False
    )

    # Percentage of traffic routed to version_a (0–100)
    traffic_split_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=50)

    # status: "active" | "paused" | "completed"
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")

    # Aggregate metrics (updated by background job)
    version_a_sessions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version_b_sessions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version_a_avg_rating: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    version_b_avg_rating: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    concluded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    winner_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "agent_id": str(self.agent_id),
            "name": self.name,
            "description": self.description,
            "version_a_id": str(self.version_a_id),
            "version_b_id": str(self.version_b_id),
            "traffic_split_percent": self.traffic_split_percent,
            "status": self.status,
            "version_a_sessions": self.version_a_sessions,
            "version_b_sessions": self.version_b_sessions,
            "version_a_avg_rating": round(self.version_a_avg_rating, 4),
            "version_b_avg_rating": round(self.version_b_avg_rating, 4),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "concluded_at": self.concluded_at.isoformat() if self.concluded_at else None,
            "winner_version_id": str(self.winner_version_id) if self.winner_version_id else None,
        }
