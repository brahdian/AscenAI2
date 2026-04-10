"""Add case-insensitive unique index on lower(email) for users table.

Revision ID: 0002
Revises: 0001
Create Date: 2026-01-01 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the old case-sensitive unique index (if it exists) and replace with
    # a functional index on lower(email) so that duplicate emails differing
    # only in case are correctly rejected.
    op.execute(
        "DROP INDEX IF EXISTS ix_users_email;"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email_lower "
        "ON users (lower(email));"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_users_email_lower;")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users (email);"
    )
