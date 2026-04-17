"""Create billing_events table for durable usage tracking.

Revision ID: 0017
Revises: 0016
Create Date: 2026-04-17 00:00:00.000000

Why: BillingService previously wrote usage (tokens, chats, voice minutes, tool
calls) only to Redis with a 32-day TTL.  A Redis flush, restart, or OOM-eviction
permanently destroyed all current-month billing data — revenue loss and
reconciliation failures.

This migration adds a durable append-only event log.  The BillingService now
writes every usage event here AS WELL AS to Redis.  Redis remains the fast read
path for quota enforcement; this table is the authoritative source of truth for
billing reconciliation.

Schema notes:
- event_type: 'token' | 'chat' | 'voice_minute' | 'tool_call'
- amount: raw quantity (tokens, chat units, seconds, tool count)
- month_key: 'YYYY-MM' partition key for efficient monthly queries
- created_at: UTC timestamp of the event
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "billing_events",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("month_key", sa.String(7), nullable=False),   # 'YYYY-MM'
        sa.Column("session_id", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
    )
    op.create_index(
        "ix_billing_events_tenant_month",
        "billing_events",
        ["tenant_id", "month_key"],
    )

    # RLS — each tenant can only see their own billing events
    op.execute("ALTER TABLE billing_events ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON billing_events;")
    op.execute("""
        CREATE POLICY tenant_isolation ON billing_events
        USING (tenant_id = current_tenant_id())
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON billing_events;")
    op.execute("ALTER TABLE billing_events DISABLE ROW LEVEL SECURITY;")
    op.drop_index("ix_billing_events_tenant_month", table_name="billing_events")
    op.drop_table("billing_events")
