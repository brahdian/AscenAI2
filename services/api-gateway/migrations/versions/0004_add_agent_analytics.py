"""Add agent_analytics table

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-02 20:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if not inspector.has_table("agent_analytics"):
        op.create_table(
            "agent_analytics",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "tenant_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("date", sa.Date(), nullable=False),
            sa.Column("total_sessions", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("total_messages", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("total_chat_units", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("total_voice_minutes", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_agent_analytics_tenant_date", "agent_analytics", ["tenant_id", "date"])
        op.create_index("ix_agent_analytics_agent_date", "agent_analytics", ["agent_id", "date"])


def downgrade() -> None:
    op.drop_table("agent_analytics")
