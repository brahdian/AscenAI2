"""Migration placeholder - already merged into 0012.

Revision ID: 0011
Revises: 0010
Create Date: 2026-04-06 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
