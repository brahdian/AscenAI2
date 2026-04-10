"""Enable Row Level Security (RLS) on tenant tables.

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-03 14:16:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0007'
down_revision: Union[str, None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Function to grab the tenant ID from the session config
    op.execute("""
        CREATE OR REPLACE FUNCTION current_tenant_id() RETURNS UUID AS $$
        BEGIN
            RETURN current_setting('app.current_tenant_id', TRUE)::UUID;
        EXCEPTION
            WHEN invalid_text_representation OR undefined_object THEN
                RETURN NULL;
        END;
        $$ LANGUAGE plpgsql STABLE SECURITY DEFINER;
    """)

    rls_tables = [
        "tenant_usage",
        "users",
        "api_keys",
        "webhooks"
    ]

    for tbl in rls_tables:
        op.execute(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {tbl};")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {tbl}
            USING (tenant_id = current_tenant_id())
        """)


def downgrade() -> None:
    rls_tables = [
        "tenant_usage",
        "users",
        "api_keys",
        "webhooks"
    ]

    for tbl in rls_tables:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {tbl};")
        op.execute(f"ALTER TABLE {tbl} DISABLE ROW LEVEL SECURITY;")
    
    op.execute("DROP FUNCTION IF EXISTS current_tenant_id();")
