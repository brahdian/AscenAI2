"""
AuditLog — persistent record of every significant action in the platform.

Required by:
  - SOC2 Type II  (CC6.1, CC7.2 — logical access monitoring, system monitoring)
  - GDPR Art. 30  (records of processing activities)
  - HIPAA §164.312(b) (audit controls)
  - PCI-DSS 10.2  (implement audit logs)

Every admin action, login event, role change, data export, or sensitive
mutation should produce an AuditLog row via audit_log() in audit_service.py.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        # Fast lookup by tenant + time range (primary access pattern for compliance reports)
        Index("ix_audit_logs_tenant_created", "tenant_id", "created_at"),
        # Fast lookup by acting user
        Index("ix_audit_logs_user_id", "actor_user_id"),
        # Fast lookup by resource (e.g., find all events on a specific agent)
        Index("ix_audit_logs_resource", "resource_type", "resource_id"),
        # Fast lookup by action category
        Index("ix_audit_logs_action", "action"),
        # Advanced composite index for common dashboard filter permutations (Pass 8)
        Index("ix_audit_logs_advanced_filter", "tenant_id", "category", "status", "is_support_access", "created_at"),
    )


    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Tenant the event belongs to.  NULL for platform-level events (e.g., super-admin actions).
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # User who performed the action.  NULL for system/automated actions.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Human-readable actor identifier (email or "system") — denormalised for
    # readability in exported reports without needing a JOIN.
    actor_email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    actor_role: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Forensic signature: True if the action was performed by a support person
    # (using Impersonation or Admin access), False for normal tenant users.
    is_support_access: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")

    # Action performed.  Use namespaced dot-notation, e.g.:
    #   auth.login_success, auth.login_failed, auth.logout
    #   user.role_changed, user.password_reset
    #   tenant.suspended, tenant.deleted
    #   agent.created, agent.deleted
    #   admin.guardrail_disabled, admin.platform_setting_changed
    #   data.export, data.erasure
    action: Mapped[str] = mapped_column(String(100), nullable=False)

    # Category for filtering: auth | user | tenant | agent | billing | admin | data | api_key
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="general")

    # The resource this action targeted.
    resource_type: Mapped[str | None] = mapped_column(String(50), nullable=True)  # "agent", "user", etc.
    resource_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Outcome of the action.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="success")  # success | failure

    # Freeform details — keep small.  Do NOT store PII or credentials here.
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Network context
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)   # IPv4 or IPv6
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return f"<AuditLog action={self.action} actor={self.actor_email} at={self.created_at}>"
