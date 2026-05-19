"""add conversation_log table

Revision ID: daee4d3832d5
Revises: 005_fix_assignment_constraint
Create Date: 2026-05-18 21:46:08.467319+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'daee4d3832d5'
down_revision: Union[str, None] = '005_fix_assignment_constraint'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'conversation_log',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('operator_id', sa.Integer(), nullable=False),
        sa.Column('machine_id', sa.Integer(), nullable=True),
        sa.Column('raw_text', sa.Text(), nullable=False),
        sa.Column('intent', sa.String(length=64), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('policy_action', sa.String(length=32), nullable=True),
        sa.Column('task_type', sa.String(length=8), nullable=True),
        sa.Column('vfm_reply', sa.Text(), nullable=True),
        sa.Column('source', sa.String(length=32), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['machine_id'], ['machines.id']),
        sa.ForeignKeyConstraint(['operator_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_conv_log_operator_date', 'conversation_log', ['operator_id', 'created_at'])
    op.create_index('ix_conversation_log_created_at', 'conversation_log', ['created_at'])
    op.create_index('ix_conversation_log_operator_id', 'conversation_log', ['operator_id'])


def downgrade() -> None:
    op.drop_index('ix_conversation_log_operator_id', table_name='conversation_log')
    op.drop_index('ix_conversation_log_created_at', table_name='conversation_log')
    op.drop_index('idx_conv_log_operator_date', table_name='conversation_log')
    op.drop_table('conversation_log')
