"""
Alembic migration: Hardening schema additions
=============================================

Adds:
  1. `processed_events` table  — DB-backed idempotency store (Phase 2)
  2. `agent_state_transitions` table — Agent state audit log (Phase 3)
  3. `stripe_session_id` unique constraint on `pending_agent_purchases` (Phase 2)
  4. GIN index on `agents.agent_config` JSONB (Phase 8)
  5. GIN index on `playbook_executions.variables` JSONB (Phase 8)

Revision: 0001_hardening
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = "0001_hardening"
down_revision = None   # set to your latest migration head if one exists
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # 1. processed_events — idempotency store                             #
    # ------------------------------------------------------------------ #
    op.create_table(
        "processed_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("namespace", sa.String(100), nullable=False),
        sa.Column("event_key", sa.String(255), nullable=False),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_processed_events_ns_key",
        "processed_events",
        ["namespace", "event_key"],
        unique=True,
    )
    op.create_index(
        "ix_processed_events_processed_at",
        "processed_events",
        ["processed_at"],
    )

    # ------------------------------------------------------------------ #
    # 2. agent_state_transitions — state machine audit log                #
    # ------------------------------------------------------------------ #
    op.create_table(
        "agent_state_transitions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "agent_id",
            UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("from_state", sa.String(30), nullable=False),
        sa.Column("to_state", sa.String(30), nullable=False),
        sa.Column("reason", sa.Text, nullable=False, server_default=""),
        sa.Column("actor", sa.String(100), nullable=False, server_default="system"),
        sa.Column(
            "transitioned_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_ast_agent_id", "agent_state_transitions", ["agent_id"])
    op.create_index("ix_ast_tenant_id", "agent_state_transitions", ["tenant_id"])
    op.create_index(
        "ix_ast_transitioned_at", "agent_state_transitions", ["transitioned_at"]
    )
    op.create_index("ix_ast_to_state", "agent_state_transitions", ["to_state"])

    # ------------------------------------------------------------------ #
    # 3. pending_agent_purchases — add stripe_session_id for idempotency  #
    # ------------------------------------------------------------------ #
    op.add_column(
        "pending_agent_purchases",
        sa.Column("stripe_session_id", sa.String(255), nullable=True),
    )
    op.create_index(
        "uq_pending_agent_purchase_stripe_session",
        "pending_agent_purchases",
        ["stripe_session_id"],
        unique=True,
        postgresql_where=sa.text("stripe_session_id IS NOT NULL"),
    )

    # ------------------------------------------------------------------ #
    # 4. GIN index on agents.agent_config JSONB                           #
    # ------------------------------------------------------------------ #
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_agents_agent_config_gin "
        "ON agents USING gin (agent_config jsonb_path_ops)"
    )

    # ------------------------------------------------------------------ #
    # 5. GIN index on playbook_executions.variables JSONB                 #
    # ------------------------------------------------------------------ #
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_pb_exec_variables_gin "
        "ON playbook_executions USING gin (variables jsonb_path_ops)"
    )

    # ------------------------------------------------------------------ #
    # 6. Add status column default normalisation to agents table           #
    # ------------------------------------------------------------------ #
    # Ensure existing rows without a status default to 'DRAFT'
    op.execute(
        "UPDATE agents SET status = 'DRAFT' WHERE status IS NULL OR status = ''"
    )


def downgrade() -> None:
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_pb_exec_variables_gin")
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_agents_agent_config_gin")
    op.drop_index("uq_pending_agent_purchase_stripe_session", "pending_agent_purchases")
    op.drop_column("pending_agent_purchases", "stripe_session_id")
    op.drop_table("agent_state_transitions")
    op.drop_table("processed_events")
