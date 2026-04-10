"""
AgentStateTransition model
===========================
Immutable audit log of every Agent.status change.
One row per transition. Never updated, only appended.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AgentStateTransition(Base):
    """
    Append-only audit log of every agent state-machine transition.

    Attributes
    ----------
    from_state:
        State before the transition.
    to_state:
        State after the transition.
    reason:
        Human-readable context string (e.g. "stripe_payment_confirmed").
    actor:
        Who triggered the transition (e.g. "billing_webhook", "admin_api", "system").
    """

    __tablename__ = "agent_state_transitions"
    __table_args__ = (
        Index("ix_ast_agent_id", "agent_id"),
        Index("ix_ast_tenant_id", "tenant_id"),
        Index("ix_ast_transitioned_at", "transitioned_at"),
        Index("ix_ast_to_state", "to_state"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )

    from_state: Mapped[str] = mapped_column(String(30), nullable=False)
    to_state: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    actor: Mapped[str] = mapped_column(String(100), nullable=False, default="system")

    transitioned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "agent_id": str(self.agent_id),
            "tenant_id": str(self.tenant_id),
            "from_state": self.from_state,
            "to_state": self.to_state,
            "reason": self.reason,
            "actor": self.actor,
            "transitioned_at": self.transitioned_at.isoformat() if self.transitioned_at else None,
        }
