"""Extend RLS with full coverage and WITH CHECK constraint.

Revision ID: 0025
Revises: 0024
Create Date: 2026-04-27 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = '0025'
down_revision: Union[str, None] = '0024'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Tables that already have RLS (need their policies updated to include WITH CHECK)
_EXISTING_RLS_TABLES = [
    "users",
    "api_keys",
    "webhooks",
    "tenant_usage",
    "pending_agent_purchases"
]

# New tables to enable RLS on
_NEW_RLS_TABLES = [
    "agents",
    "agent_analytics",
    "agent_playbooks",
    "tenant_crm_workspaces",
    "playbook_executions",
    "mcp_tools",
    "mcp_tool_executions",
    "messages",
    "sessions"
]


def upgrade() -> None:
    # 1. Update existing policies to add WITH CHECK
    for tbl in _EXISTING_RLS_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {tbl};")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {tbl}
            USING (tenant_id = current_tenant_id())
            WITH CHECK (tenant_id = current_tenant_id())
        """)

    # 2. Enable RLS on new tables and add full policy
    for tbl in _NEW_RLS_TABLES:
        op.execute(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {tbl};")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {tbl}
            USING (tenant_id = current_tenant_id())
            WITH CHECK (tenant_id = current_tenant_id())
        """)


def downgrade() -> None:
    # Revert new tables
    for tbl in _NEW_RLS_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {tbl};")
        op.execute(f"ALTER TABLE {tbl} DISABLE ROW LEVEL SECURITY;")
        
    # Revert existing tables back to using only USING
    for tbl in _EXISTING_RLS_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {tbl};")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {tbl}
            USING (tenant_id = current_tenant_id())
        """)
