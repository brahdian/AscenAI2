"""Synchronize schema with ORM models by adding missing Stripe and usage columns.

Revision ID: 0013
Revises: 0012
Create Date: 2026-04-07 07:20:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # 1. Add missing Stripe columns to tenants table
    # -------------------------------------------------------------------------
    op.execute(sa.text("""
        ALTER TABLE tenants 
        ADD COLUMN IF NOT EXISTS stripe_customer_id VARCHAR(255),
        ADD COLUMN IF NOT EXISTS subscription_status VARCHAR(50),
        ADD COLUMN IF NOT EXISTS subscription_id VARCHAR(255)
    """))

    # -------------------------------------------------------------------------
    # 2. Add current_month_chat_units to tenant_usage
    # -------------------------------------------------------------------------
    op.execute(sa.text("""
        ALTER TABLE tenant_usage 
        ADD COLUMN IF NOT EXISTS current_month_chat_units INTEGER NOT NULL DEFAULT 0
    """))

    # -------------------------------------------------------------------------
    # 3. Add is_email_verified to users
    # -------------------------------------------------------------------------
    op.execute(sa.text("""
        ALTER TABLE users 
        ADD COLUMN IF NOT EXISTS is_email_verified BOOLEAN NOT NULL DEFAULT FALSE
    """))

    # -------------------------------------------------------------------------
    # 4. Add rate_limit_per_minute to api_keys
    # -------------------------------------------------------------------------
    op.execute(sa.text("""
        ALTER TABLE api_keys 
        ADD COLUMN IF NOT EXISTS rate_limit_per_minute INTEGER NOT NULL DEFAULT 60
    """))


def downgrade() -> None:
    op.drop_column("api_keys", "rate_limit_per_minute")
    op.drop_column("users", "is_email_verified")
    op.drop_column("tenant_usage", "current_month_chat_units")
    op.drop_column("tenants", "subscription_id")
    op.drop_column("tenants", "subscription_status")
    op.drop_column("tenants", "stripe_customer_id")
