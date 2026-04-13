"""Add booking_workflows and booking_events tables.

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-13 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create the booking_state enum type
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE booking_state AS ENUM (
                'INITIATED',
                'SLOT_HELD',
                'PAYMENT_PENDING',
                'PAYMENT_COMPLETED',
                'CONFIRMED',
                'EXPIRED',
                'FAILED',
                'NEEDS_REBOOK'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
        """
    )

    # --- booking_workflows ---------------------------------------------------
    op.create_table(
        "booking_workflows",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("customer_name", sa.String(255), nullable=False),
        sa.Column("customer_phone", sa.String(32), nullable=False, server_default=""),
        sa.Column("customer_email", sa.String(320), nullable=False, server_default=""),
        sa.Column("provider", sa.String(64), nullable=False, server_default="builtin"),
        sa.Column("external_reservation_id", sa.Text, nullable=True),
        sa.Column("external_reservation_url", sa.Text, nullable=True),
        sa.Column("slot_service", sa.String(255), nullable=False),
        sa.Column("slot_date", sa.Date, nullable=False),
        sa.Column("slot_time", sa.String(10), nullable=False),
        sa.Column("slot_duration_minutes", sa.Integer, nullable=False, server_default="60"),
        sa.Column(
            "state",
            postgresql.ENUM(
                "INITIATED", "SLOT_HELD", "PAYMENT_PENDING", "PAYMENT_COMPLETED",
                "CONFIRMED", "EXPIRED", "FAILED", "NEEDS_REBOOK",
                name="booking_state", create_type=False,
            ),
            nullable=False,
            server_default="INITIATED",
        ),
        sa.Column("state_version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("payment_idempotency_key", sa.String(128), nullable=False),
        sa.Column("payment_link_url", sa.Text, nullable=True),
        sa.Column("payment_intent_id", sa.String(128), nullable=True),
        sa.Column("expiry_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sms_reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "extra_metadata", postgresql.JSONB, nullable=False, server_default="{}"
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
    )
    op.create_unique_constraint(
        "uq_bw_payment_intent_id", "booking_workflows", ["payment_intent_id"]
    )
    op.create_index("ix_bw_tenant_state", "booking_workflows", ["tenant_id", "state"])
    op.execute(
        """
        CREATE INDEX ix_bw_expiry_active
        ON booking_workflows (expiry_time)
        WHERE state NOT IN ('CONFIRMED', 'EXPIRED', 'FAILED', 'NEEDS_REBOOK');
        """
    )

    # --- booking_events ------------------------------------------------------
    op.create_table(
        "booking_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workflow_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("booking_workflows.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("from_state", sa.String(64), nullable=True),
        sa.Column("to_state", sa.String(64), nullable=True),
        sa.Column("actor", sa.String(64), nullable=False, server_default="system"),
        sa.Column("idempotency_key", sa.String(255), nullable=True),
        sa.Column(
            "payload", postgresql.JSONB, nullable=False, server_default="{}"
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
    )
    op.create_unique_constraint(
        "uq_be_idempotency_key", "booking_events", ["idempotency_key"]
    )
    op.create_index("ix_be_workflow_id", "booking_events", ["workflow_id"])
    op.create_index("ix_be_event_type", "booking_events", ["event_type"])


def downgrade() -> None:
    op.drop_table("booking_events")
    op.drop_table("booking_workflows")
    op.execute("DROP TYPE IF EXISTS booking_state")
