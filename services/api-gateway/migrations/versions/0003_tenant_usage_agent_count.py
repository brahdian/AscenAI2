"""Add agent_count to tenant_usage for plan limit enforcement.

Revision ID: 0003
Revises: 0002
Create Date: 2026-01-01 00:00:00.000000

agent_count tracks how many active agents a tenant has so we can enforce
plan limits (max_agents) without querying the orchestrator service.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tenant_usage",
        sa.Column("agent_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("tenant_usage", "agent_count")
