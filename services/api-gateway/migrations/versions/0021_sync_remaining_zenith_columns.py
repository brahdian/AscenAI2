"""Sync remaining Zenith columns.

Revision ID: 0021
Revises: 0020
Create Date: 2026-04-19 16:30:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Tenants Table ──
    # audit_retention_days is required for compliance purging
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS audit_retention_days INTEGER NOT NULL DEFAULT 365")
    # metadata is used for arbitrary tenant configuration
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb")

    # ── Users Table ──
    # avatar_url for profile pictures
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_url VARCHAR(2048)")
    # session_version for global sign-out
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS session_version INTEGER NOT NULL DEFAULT 1")
    # mfa_enabled for security hardening
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS mfa_enabled BOOLEAN NOT NULL DEFAULT FALSE")
    # forensic timestamps
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMP WITH TIME ZONE")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS password_changed_at TIMESTAMP WITH TIME ZONE")

    # ── API Keys Table ──
    # agent_id for key restriction
    op.execute("ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS agent_id UUID")
    # allowed_origins for CORS
    op.execute("ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS allowed_origins JSONB NOT NULL DEFAULT '[]'::jsonb")


def downgrade() -> None:
    # No-op for recovery safety to avoid accidental data loss during schema repair
    pass
