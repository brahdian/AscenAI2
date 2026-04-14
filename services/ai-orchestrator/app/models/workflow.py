"""Workflow engine models — general-purpose DAG-based automation workflows.

Tables
------
workflows              — definition: nodes, edges, entry_node_id, variables
workflow_executions    — one row per execution instance (state machine)
workflow_step_executions — per-node audit log with idempotency guard
workflow_events        — append-only event log for every status change

Design principles
-----------------
* Workflows are stored as JSONB DAGs — nodes + directed edges.
* WorkflowExecution is the running instance; status follows RUNNING →
  AWAITING_INPUT | AWAITING_EVENT → COMPLETED | FAILED | EXPIRED.
* WorkflowStepExecution.idempotency_key (execution_id:node_id) makes
  every node execution idempotent — safe to re-run on crash/replay.
* Active workflows auto-register as wf:<id> MCP tools via WorkflowRegistry.
* The workflow UUID is the stable, immutable, globally-unique tool identifier.
  MCP tool name = wf:{workflow.id}. No slug — use name/description for display.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,  # still used by WorkflowStepExecution and WorkflowEvent
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ExecutionStatus(str, enum.Enum):
    RUNNING          = "RUNNING"
    AWAITING_INPUT   = "AWAITING_INPUT"
    AWAITING_EVENT   = "AWAITING_EVENT"   # waiting for webhook / SMS reply / delay
    COMPLETED        = "COMPLETED"
    FAILED           = "FAILED"
    EXPIRED          = "EXPIRED"


TERMINAL_EXECUTION_STATUSES = {
    ExecutionStatus.COMPLETED,
    ExecutionStatus.FAILED,
    ExecutionStatus.EXPIRED,
}


class StepStatus(str, enum.Enum):
    RUNNING   = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED    = "FAILED"
    SKIPPED   = "SKIPPED"


# ---------------------------------------------------------------------------
# Workflow — definition (the "program")
# ---------------------------------------------------------------------------

class Workflow(Base):
    """Immutable-ish workflow definition (bumps version on update).

    Activate to register as an LLM-callable MCP tool: wf:<id>.
    The UUID is the canonical, immutable, globally-unique tool identifier.
    """
    __tablename__ = "workflows"
    __table_args__ = (
        Index("ix_wf_agent_active", "agent_id", "is_active"),
        Index("ix_wf_tenant_id", "tenant_id"),
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

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Shown to the LLM as the tool description when is_active=True
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Bumped on every PUT — executions pin to the version at creation time
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # JSONB DAG: {nodes: [...], edges: [...], entry_node_id: str, variables: {}}
    definition: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # JSON Schema for LLM-facing tool inputs (what the LLM must pass in)
    input_schema: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # JSON Schema for tool outputs (informational)
    output_schema: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Arbitrary tags for filtering: ["booking", "payment"]
    tags: Mapped[dict] = mapped_column(JSONB, nullable=False, default=list)

    # ── Trigger configuration ────────────────────────────────────────────────
    # "none"    — triggered only by LLM tool call (default conversational flow)
    # "cron"    — fired by WorkflowTriggerWorker on a schedule
    # "webhook" — fired by POST /flows/{id}/trigger (HMAC-verified)
    # "event"   — fired by internal event bus (e.g. "payment.completed")
    trigger_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="none"
    )
    # {"schedule": "0 9 * * *", "timezone": "UTC"}         for cron
    # {"webhook_secret": "whsec_..."}                       for webhook
    # {"event": "payment.completed", "filter": {...}}       for event
    trigger_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # ── Execution provenance (set on WorkflowExecution, mirrored here) ───────
    # Informational: last_triggered_at for monitoring dashboards
    last_triggered_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    executions: Mapped[list[WorkflowExecution]] = relationship(
        "WorkflowExecution", back_populates="workflow", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<Workflow id={self.id!s:.8} name={self.name!r} "
            f"active={self.is_active} v={self.version}>"
        )


# ---------------------------------------------------------------------------
# WorkflowExecution — running instance (the "process")
# ---------------------------------------------------------------------------

class WorkflowExecution(Base):
    """One row per invocation of a workflow.

    Lifecycle
    ---------
    RUNNING → AWAITING_INPUT → RUNNING (on user reply)
    RUNNING → AWAITING_EVENT → RUNNING (on webhook/SMS reply/delay expiry)
    RUNNING → COMPLETED | FAILED
    AWAITING_* → EXPIRED (via expiry worker)
    """
    __tablename__ = "workflow_executions"
    __table_args__ = (
        Index("ix_wfexec_session_id", "session_id"),
        Index("ix_wfexec_tenant_status", "tenant_id", "status"),
        Index("ix_wfexec_workflow_id", "workflow_id"),
        # Partial index for expiry worker — only non-terminal executions
        Index(
            "ix_wfexec_expiry_active",
            "expiry_time",
            postgresql_where=(
                "status NOT IN ('COMPLETED','FAILED','EXPIRED')"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    # Original session that started this execution
    session_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Customer contact — stored for post-disconnect SMS automation
    customer_phone: Mapped[str] = mapped_column(String(32), nullable=False, default="")

    # How this execution was started
    # "llm_tool_call" | "cron" | "webhook" | "event" | "manual_api"
    trigger_source: Mapped[str] = mapped_column(
        String(30), nullable=False, default="llm_tool_call"
    )

    # Short opaque token for resuming AWAITING_EVENT executions from SMS replies.
    # Format: "r-{8 random chars}". Stored in Redis: phone → execution_id (TTL).
    resumption_token: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True, index=True
    )

    # Current position in the DAG
    current_node_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    status: Mapped[ExecutionStatus] = mapped_column(
        SAEnum(ExecutionStatus, name="execution_status", create_type=True),
        nullable=False,
        default=ExecutionStatus.RUNNING,
    )

    # All workflow variables — inputs + accumulated outputs from nodes
    context: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Ordered list of node execution snapshots for replay/debugging
    history: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # TTL for AWAITING_EVENT states (delay nodes, SMS await-reply)
    expiry_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    sms_reminder_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    workflow: Mapped[Workflow] = relationship("Workflow", back_populates="executions")
    step_executions: Mapped[list[WorkflowStepExecution]] = relationship(
        "WorkflowStepExecution",
        back_populates="execution",
        cascade="all, delete-orphan",
        order_by="WorkflowStepExecution.started_at",
    )
    events: Mapped[list[WorkflowEvent]] = relationship(
        "WorkflowEvent",
        back_populates="execution",
        cascade="all, delete-orphan",
        order_by="WorkflowEvent.created_at",
    )

    def __repr__(self) -> str:
        return (
            f"<WorkflowExecution id={self.id!s:.8} "
            f"workflow={self.workflow_id!s:.8} status={self.status.value}>"
        )


# ---------------------------------------------------------------------------
# WorkflowStepExecution — per-node audit log
# ---------------------------------------------------------------------------

class WorkflowStepExecution(Base):
    """Immutable record of a single node execution within a workflow run.

    The `idempotency_key` unique constraint (execution_id:node_id) ensures
    each node is only executed once — safe to re-execute on crash replay.
    """
    __tablename__ = "workflow_step_executions"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_wfstep_idempotency_key"),
        Index("ix_wfstep_execution_id", "execution_id"),
        Index("ix_wfstep_node_type", "node_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflow_executions.id", ondelete="CASCADE"),
        nullable=False,
    )

    node_id: Mapped[str] = mapped_column(String(255), nullable=False)
    node_type: Mapped[str] = mapped_column(String(50), nullable=False)

    status: Mapped[StepStatus] = mapped_column(
        SAEnum(StepStatus, name="step_status", create_type=True),
        nullable=False,
        default=StepStatus.RUNNING,
    )

    # Snapshots of context before/after execution (PII-scrubbed before write)
    input_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    output_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Wall-clock execution time in milliseconds
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # "{execution_id}:{node_id}" — unique constraint prevents duplicate execution
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationship
    execution: Mapped[WorkflowExecution] = relationship(
        "WorkflowExecution", back_populates="step_executions"
    )

    def __repr__(self) -> str:
        return (
            f"<WorkflowStepExecution node={self.node_id} "
            f"type={self.node_type} status={self.status.value}>"
        )


# ---------------------------------------------------------------------------
# WorkflowEvent — append-only event log
# ---------------------------------------------------------------------------

class WorkflowEvent(Base):
    """Immutable audit record for every execution status change and node event.

    The `idempotency_key` unique constraint makes every write idempotent
    (INSERT … ON CONFLICT DO NOTHING pattern).
    """
    __tablename__ = "workflow_events"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_wfevt_idempotency_key"),
        Index("ix_wfevt_execution_id", "execution_id"),
        Index("ix_wfevt_event_type", "event_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflow_executions.id", ondelete="CASCADE"),
        nullable=False,
    )

    # NODE_STARTED, NODE_COMPLETED, NODE_FAILED, AWAITING_INPUT,
    # AWAITING_EVENT, EXECUTION_COMPLETED, EXECUTION_FAILED, SMS_SENT, etc.
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)

    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # "system" | "user" | "webhook" | "expiry_worker" | "llm"
    actor: Mapped[str] = mapped_column(String(100), nullable=False, default="system")

    # Unique key prevents duplicate event inserts
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationship
    execution: Mapped[WorkflowExecution] = relationship(
        "WorkflowExecution",
        back_populates="events",
    )

    def __repr__(self) -> str:
        return (
            f"<WorkflowEvent type={self.event_type} "
            f"execution={self.execution_id!s:.8}>"
        )
