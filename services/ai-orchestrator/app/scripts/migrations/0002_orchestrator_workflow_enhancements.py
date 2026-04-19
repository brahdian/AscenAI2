"""
Alembic migration: Orchestrator workflow enhancements
=====================================================

Adds new columns to `workflow_executions` to support:

  1. `parent_execution_id` (UUID, nullable, FK → workflow_executions.id)
     Links sub-workflow executions back to the parent that spawned them.
     Used for full call-chain tracing in the CALL_WORKFLOW and PARALLEL nodes.

  2. `signal_name` (VARCHAR 255, nullable, indexed)
     The correlated signal name a WAIT_FOR_SIGNAL execution is waiting for.
     The signal delivery endpoint queries this field to resume the execution.

Revision : 0002_orchestrator_workflow_enhancements
Previous : 0001_hardening
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = "0002_orchestrator_workflow_enhancements"
down_revision = "0001_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # 1. parent_execution_id — sub-workflow tracing                        #
    # ------------------------------------------------------------------ #
    op.add_column(
        "workflow_executions",
        sa.Column(
            "parent_execution_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflow_executions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_wfexec_parent_execution_id",
        "workflow_executions",
        ["parent_execution_id"],
        postgresql_where=sa.text("parent_execution_id IS NOT NULL"),
    )

    # ------------------------------------------------------------------ #
    # 2. signal_name — WAIT_FOR_SIGNAL correlation                        #
    # ------------------------------------------------------------------ #
    op.add_column(
        "workflow_executions",
        sa.Column("signal_name", sa.String(255), nullable=True),
    )
    op.create_index(
        "ix_wfexec_signal_name",
        "workflow_executions",
        ["signal_name"],
        postgresql_where=sa.text("signal_name IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_wfexec_signal_name", table_name="workflow_executions")
    op.drop_column("workflow_executions", "signal_name")
    op.drop_index(
        "ix_wfexec_parent_execution_id", table_name="workflow_executions"
    )
    op.drop_column("workflow_executions", "parent_execution_id")
