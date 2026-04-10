"""Add is_sensitive, is_public, supported_languages to platform_settings; add password_changed_at to users.

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-05 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # 1. platform_settings — add columns missing from existing deployments.
    #    Skipped on fresh installs (table created by SQLAlchemy init_db with
    #    all columns already present via the ORM model).
    # -------------------------------------------------------------------------
    op.execute(sa.text("""
        DO $$ BEGIN
          IF EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_name = 'platform_settings'
          ) THEN
            ALTER TABLE platform_settings ADD COLUMN IF NOT EXISTS is_sensitive BOOLEAN NOT NULL DEFAULT FALSE;
            ALTER TABLE platform_settings ADD COLUMN IF NOT EXISTS is_public BOOLEAN NOT NULL DEFAULT FALSE;
            ALTER TABLE platform_settings ADD COLUMN IF NOT EXISTS supported_languages JSONB NOT NULL DEFAULT '[]'::jsonb;
          END IF;
        END $$;
    """))

    # -------------------------------------------------------------------------
    # 2. users — add password_changed_at. Also guarded for fresh installs.
    # -------------------------------------------------------------------------
    op.execute(sa.text("""
        DO $$ BEGIN
          IF EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_name = 'users'
          ) THEN
            ALTER TABLE users ADD COLUMN IF NOT EXISTS password_changed_at TIMESTAMPTZ;
          END IF;
        END $$;
    """))


def downgrade() -> None:
    op.execute(sa.text("ALTER TABLE users DROP COLUMN IF EXISTS password_changed_at"))
    op.execute(sa.text("ALTER TABLE platform_settings DROP COLUMN IF EXISTS supported_languages"))
    op.execute(sa.text("ALTER TABLE platform_settings DROP COLUMN IF EXISTS is_public"))
    op.execute(sa.text("ALTER TABLE platform_settings DROP COLUMN IF EXISTS is_sensitive"))
