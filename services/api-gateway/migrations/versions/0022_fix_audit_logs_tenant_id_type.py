"""Fix audit_logs tenant_id type drift.

Converts audit_logs.tenant_id from VARCHAR to UUID to resolve operator mismatch 
errors in background purge scripts and ensure schema parity with the ORM.

Revision ID: 0022
Revises: 0021
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Ensure any non-UUID values are cleaned up (empty strings)
    op.execute(sa.text(
        "UPDATE audit_logs SET tenant_id = NULL WHERE tenant_id::text = ''"
    ))
    op.execute(sa.text(
        "UPDATE audit_logs SET actor_user_id = NULL WHERE actor_user_id::text = ''"
    ))
    
    # 2. Convert column type with explicit USING clause
    op.execute(sa.text(
        "ALTER TABLE audit_logs ALTER COLUMN tenant_id TYPE UUID USING tenant_id::UUID"
    ))
    
    # 3. Ensure actor_user_id is also strictly UUID
    op.execute(sa.text(
        "ALTER TABLE audit_logs ALTER COLUMN actor_user_id TYPE UUID USING actor_user_id::UUID"
    ))

    # 4. Add missing columns for SOC2/Zenith hardening
    op.execute(sa.text(
        "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS is_support_access BOOLEAN NOT NULL DEFAULT FALSE"
    ))

    # 5. Add advanced composite indexes for analytical performance
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_audit_logs_advanced_filter "
        "ON audit_logs (tenant_id, category, status, is_support_access, created_at)"
    ))
    
    print("Migration 0022: audit_logs schema converged to UUID.")


def downgrade() -> None:
    op.execute(sa.text(
        "ALTER TABLE audit_logs ALTER COLUMN tenant_id TYPE VARCHAR(255)"
    ))
    op.execute(sa.text(
        "ALTER TABLE audit_logs ALTER COLUMN actor_user_id TYPE VARCHAR(255)"
    ))
