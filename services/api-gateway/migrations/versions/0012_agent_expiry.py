"""Add expires_at and grace_period_ends_at to agents.

Revision ID: 0012
Revises: 0011
Create Date: 2026-04-06 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("""
        ALTER TABLE agents 
        ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP WITH TIME ZONE,
        ADD COLUMN IF NOT EXISTS grace_period_ends_at TIMESTAMP WITH TIME ZONE
    """))


def downgrade() -> None:
    op.execute(sa.text("""
        ALTER TABLE agents 
        DROP COLUMN IF EXISTS grace_period_ends_at,
        DROP COLUMN IF EXISTS expires_at
    """))
