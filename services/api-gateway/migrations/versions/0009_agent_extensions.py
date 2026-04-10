"""Add extension_number and is_available_as_tool to agents

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-05
"""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE agents ADD COLUMN IF NOT EXISTS extension_number VARCHAR(20)")
    op.execute("ALTER TABLE agents ADD COLUMN IF NOT EXISTS is_available_as_tool BOOLEAN NOT NULL DEFAULT TRUE")
    op.execute("CREATE INDEX IF NOT EXISTS ix_agents_extension_number ON agents (extension_number) WHERE extension_number IS NOT NULL")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_agents_extension_number")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS extension_number")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS is_available_as_tool")
