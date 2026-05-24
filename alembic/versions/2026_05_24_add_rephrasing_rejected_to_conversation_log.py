"""add rephrasing_rejected to conversation_log

Revision ID: a1b2c3d4e5f6
Revises: daee4d3832d5
Create Date: 2026-05-24

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'daee4d3832d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'conversation_log',
        sa.Column('rephrasing_rejected', sa.Boolean(), nullable=False, server_default='false'),
    )


def downgrade() -> None:
    op.drop_column('conversation_log', 'rephrasing_rejected')
