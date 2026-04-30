"""Add Group and GroupMessage tables

Revision ID: 001_add_group_tables
Revises: 
Create Date: 2025-01-15 10:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '001_add_group_tables'
down_revision = '000_initial_tables'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create groups table
    op.create_table(
        'groups',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('group_id', sa.BigInteger(), nullable=False),
        sa.Column('group_name', sa.String(255), nullable=False),
        sa.Column('owner_id', sa.Integer(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('group_id')
    )
    op.create_index('idx_groups_owner', 'groups', ['owner_id'])
    
    # Create group_messages table
    op.create_table(
        'group_messages',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('group_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('telegram_user_id', sa.BigInteger(), nullable=False),
        sa.Column('username', sa.String(100), nullable=True),
        sa.Column('first_name', sa.String(100), nullable=True),
        sa.Column('last_name', sa.String(100), nullable=True),
        sa.Column('telegram_message_id', sa.BigInteger(), nullable=False),
        sa.Column('message_text', sa.Text(), nullable=False),
        sa.Column('message_type', sa.String(50), nullable=False),
        sa.Column('reply_to_message_id', sa.BigInteger(), nullable=True),
        sa.Column('original_sender', sa.String(255), nullable=True),
        sa.Column('parsed_data', sa.Text(), nullable=True),
        sa.Column('processing_status', sa.String(50), nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['group_id'], ['groups.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('telegram_message_id')
    )
    op.create_index('idx_group_messages_date_group', 'group_messages', ['created_at', 'group_id'])
    op.create_index('idx_group_messages_user_date', 'group_messages', ['telegram_user_id', 'created_at'])
    op.create_index('idx_group_messages_group_id', 'group_messages', ['group_id'])
    op.create_index('idx_group_messages_user_id', 'group_messages', ['user_id'])


def downgrade() -> None:
    # Drop indexes
    op.drop_index('idx_group_messages_user_id', table_name='group_messages')
    op.drop_index('idx_group_messages_group_id', table_name='group_messages')
    op.drop_index('idx_group_messages_user_date', table_name='group_messages')
    op.drop_index('idx_group_messages_date_group', table_name='group_messages')
    
    # Drop tables
    op.drop_table('group_messages')
    
    op.drop_index('idx_groups_owner', table_name='groups')
    op.drop_table('groups')
