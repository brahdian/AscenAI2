"""Create audit_logs with correct schema; fix legacy deployments.

The audit_logs table was previously created outside of Alembic via
database.py init_db(). The original table had a different shape
(user_id VARCHAR NOT NULL, resource_type NOT NULL, missing several
columns). This migration takes ownership of the table and converges
both fresh and existing deployments to the same correct schema.

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-05 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # 1. Create table — correct schema for fresh deployments.
    #    IF NOT EXISTS is a no-op on existing deployments.
    # -------------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID,
            actor_user_id   UUID,
            actor_email     VARCHAR(255),
            actor_role      VARCHAR(50),
            action          VARCHAR(100) NOT NULL,
            category        VARCHAR(50)  NOT NULL DEFAULT 'general',
            resource_type   VARCHAR(50),
            resource_id     VARCHAR(255),
            status          VARCHAR(20)  NOT NULL DEFAULT 'success',
            details         JSONB,
            ip_address      VARCHAR(45),
            user_agent      VARCHAR(500),
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
        )
    """)

    # -------------------------------------------------------------------------
    # 2. Add any columns missing from old deployments.
    #    ADD COLUMN IF NOT EXISTS is idempotent.
    # -------------------------------------------------------------------------
    for ddl in [
        "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS actor_user_id  UUID",
        "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS actor_email    VARCHAR(255)",
        "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS actor_role     VARCHAR(50)",
        "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS category       VARCHAR(50) NOT NULL DEFAULT 'general'",
        "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS resource_type  VARCHAR(50)",
        "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS resource_id    VARCHAR(255)",
        "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS status         VARCHAR(20) NOT NULL DEFAULT 'success'",
        "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS details        JSONB",
        "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS ip_address     VARCHAR(45)",
        "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS user_agent     VARCHAR(500)",
    ]:
        op.execute(sa.text(ddl))

    # -------------------------------------------------------------------------
    # 3. Fix legacy constraint issues on old deployments.
    #
    #    a) user_id VARCHAR NOT NULL — the old primary actor column, renamed
    #       to actor_user_id (UUID).  The model never writes to user_id, so
    #       its NOT NULL constraint breaks every INSERT.  Make it nullable and
    #       give it a safe default.  Wrapped in a DO block because the column
    #       won't exist on fresh deployments (no need to alter it).
    #
    #    b) resource_type NOT NULL — old table had this required; the model
    #       sends NULL for most audit events.  DROP NOT NULL is idempotent.
    # -------------------------------------------------------------------------
    op.execute(sa.text("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'audit_logs' AND column_name = 'user_id'
            ) THEN
                ALTER TABLE audit_logs ALTER COLUMN user_id DROP NOT NULL;
                ALTER TABLE audit_logs ALTER COLUMN user_id SET DEFAULT '';
            END IF;
        END $$;
    """))

    op.execute(sa.text(
        "ALTER TABLE audit_logs ALTER COLUMN resource_type DROP NOT NULL"
    ))

    # -------------------------------------------------------------------------
    # 4. Indexes — all use IF NOT EXISTS so they are safe to re-run.
    # -------------------------------------------------------------------------
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_audit_logs_tenant_created "
        "ON audit_logs (tenant_id, created_at)"
    ))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_audit_logs_user_id "
        "ON audit_logs (actor_user_id)"
    ))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_audit_logs_resource "
        "ON audit_logs (resource_type, resource_id)"
    ))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_audit_logs_action "
        "ON audit_logs (action)"
    ))


def downgrade() -> None:
    op.drop_table("audit_logs")
