"""Add indexes for compliance erasure performance.

Revision ID: 0018
Revises: 0017
Create Date: 2026-04-18 22:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add index for customer_identifier on sessions
    op.execute("CREATE INDEX IF NOT EXISTS ix_sessions_customer_identifier ON sessions(customer_identifier)")
    # Add index for session_id on messages
    op.execute("CREATE INDEX IF NOT EXISTS ix_messages_session_id ON messages(session_id)")
    # Add index for session_id on message_feedback
    op.execute("CREATE INDEX IF NOT EXISTS ix_message_feedback_session_id ON message_feedback(session_id)")
    # Add index for session_id on conversation_traces
    op.execute("CREATE INDEX IF NOT EXISTS ix_conversation_traces_session_id ON conversation_traces(session_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_sessions_customer_identifier")
    op.execute("DROP INDEX IF EXISTS ix_messages_session_id")
    op.execute("DROP INDEX IF EXISTS ix_message_feedback_session_id")
    op.execute("DROP INDEX IF EXISTS ix_conversation_traces_session_id")
