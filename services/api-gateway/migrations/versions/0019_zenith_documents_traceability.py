"""Add Zenith forensic traceability to documents.

Revision ID: 0019
Revises: 0018
Create Date: 2026-04-19 13:30:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Zenith Pillar 1: AgentDocuments Forensic Columns ──
    op.execute("ALTER TABLE agent_documents ADD COLUMN IF NOT EXISTS created_by VARCHAR(255)")
    op.execute("ALTER TABLE agent_documents ADD COLUMN IF NOT EXISTS updated_by VARCHAR(255)")
    op.execute("ALTER TABLE agent_documents ADD COLUMN IF NOT EXISTS trace_id VARCHAR(36)")
    op.execute("ALTER TABLE agent_documents ADD COLUMN IF NOT EXISTS original_ip VARCHAR(45)")
    op.execute("ALTER TABLE agent_documents ADD COLUMN IF NOT EXISTS justification_id VARCHAR(255)")

    # ── Zenith Pillar 1: AgentDocumentChunks Trace Association ──
    op.execute("ALTER TABLE agent_document_chunks ADD COLUMN IF NOT EXISTS trace_id VARCHAR(36)")


def downgrade() -> None:
    op.execute("ALTER TABLE agent_document_chunks DROP COLUMN IF EXISTS trace_id")
    
    op.execute("ALTER TABLE agent_documents DROP COLUMN IF EXISTS justification_id")
    op.execute("ALTER TABLE agent_documents DROP COLUMN IF EXISTS original_ip")
    op.execute("ALTER TABLE agent_documents DROP COLUMN IF EXISTS trace_id")
    op.execute("ALTER TABLE agent_documents DROP COLUMN IF EXISTS updated_by")
    op.execute("ALTER TABLE agent_documents DROP COLUMN IF EXISTS created_by")
