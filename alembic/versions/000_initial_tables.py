"""Create initial core tables

Revision ID: 000_initial_tables
Revises:
Create Date: 2025-01-01 00:00:00.000000

Creates: users, machines, machine_assignments, fuel_logs, hours_logs,
         issue_reports, activity_logs, owner_settings
"""

from alembic import op
import sqlalchemy as sa

revision = '000_initial_tables'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('telegram_id', sa.BigInteger(), nullable=True, index=True),
        sa.Column('mobile', sa.String(20), nullable=False, index=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('company_name', sa.String(100), nullable=True),
        sa.Column('user_type', sa.String(20), nullable=False),
        sa.Column('owner_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True, index=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("user_type IN ('OWNER', 'OPERATOR')", name='valid_user_type'),
        sa.CheckConstraint(
            "(user_type = 'OWNER' AND owner_id IS NULL) OR "
            "(user_type = 'OPERATOR' AND owner_id IS NOT NULL)",
            name='owner_relationship_constraint',
        ),
        sa.UniqueConstraint('telegram_id', 'owner_id', name='unique_telegram_per_owner'),
    )

    op.create_table(
        'machines',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('reg_number', sa.String(20), nullable=False, unique=True, index=True),
        sa.Column('machine_type', sa.String(100), nullable=False, index=True),
        sa.Column('model', sa.String(100), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('owner_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('serial_number', sa.String(100), nullable=True),
        sa.Column('purchase_date', sa.DateTime(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.CheckConstraint('year >= 1900 AND year <= 2030', name='valid_year'),
    )

    op.create_table(
        'machine_assignments',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('machine_id', sa.Integer(), sa.ForeignKey('machines.id'), nullable=False, index=True),
        sa.Column('operator_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('assigned_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('unassigned_at', sa.DateTime(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('telegram_link_token', sa.String(100), nullable=True, unique=True, index=True),
        sa.Column('telegram_link_expires_at', sa.DateTime(), nullable=True),
        sa.Column('telegram_link_used_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('machine_id', 'is_active', name='unique_active_assignment'),
    )
    op.create_index('idx_active_assignments', 'machine_assignments', ['machine_id', 'is_active'])

    op.create_table(
        'fuel_logs',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('machine_id', sa.Integer(), sa.ForeignKey('machines.id'), nullable=False, index=True),
        sa.Column('operator_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('fuel_volume', sa.Float(), nullable=False),
        sa.Column('unit', sa.String(20), nullable=False, server_default='литров'),
        sa.Column('telegram_message_id', sa.BigInteger(), nullable=True),
        sa.Column('original_text', sa.Text(), nullable=False),
        sa.Column('parsed_data', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now(), index=True),
        sa.CheckConstraint('fuel_volume > 0', name='positive_fuel_volume'),
    )
    op.create_index('idx_fuel_logs_date_machine', 'fuel_logs', ['created_at', 'machine_id'])

    op.create_table(
        'hours_logs',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('machine_id', sa.Integer(), sa.ForeignKey('machines.id'), nullable=False, index=True),
        sa.Column('operator_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('hours', sa.Float(), nullable=False),
        sa.Column('unit', sa.String(20), nullable=False, server_default='часов'),
        sa.Column('telegram_message_id', sa.BigInteger(), nullable=True),
        sa.Column('original_text', sa.Text(), nullable=False),
        sa.Column('parsed_data', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now(), index=True),
        sa.CheckConstraint('hours > 0', name='positive_hours'),
    )
    op.create_index('idx_hours_logs_date_machine', 'hours_logs', ['created_at', 'machine_id'])

    op.create_table(
        'issue_reports',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('machine_id', sa.Integer(), sa.ForeignKey('machines.id'), nullable=False, index=True),
        sa.Column('operator_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='REPORTED'),
        sa.Column('priority', sa.String(20), nullable=False, server_default='MEDIUM'),
        sa.Column('telegram_message_id', sa.BigInteger(), nullable=True),
        sa.Column('original_text', sa.Text(), nullable=False),
        sa.Column('parsed_data', sa.Text(), nullable=True),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.Column('resolution_notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now(), index=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('REPORTED', 'IN_PROGRESS', 'RESOLVED', 'CLOSED')",
            name='valid_issue_status',
        ),
        sa.CheckConstraint(
            "priority IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')",
            name='valid_issue_priority',
        ),
    )
    op.create_index('idx_issue_reports_status_date', 'issue_reports', ['status', 'created_at'])

    op.create_table(
        'activity_logs',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('action', sa.String(100), nullable=False),
        sa.Column('entity_type', sa.String(50), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=False),
        sa.Column('details', sa.Text(), nullable=True),
        sa.Column('telegram_message_id', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now(), index=True),
    )
    op.create_index('idx_activity_logs_user_date', 'activity_logs', ['user_id', 'created_at'])

    op.create_table(
        'owner_settings',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('owner_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, unique=True),
        sa.Column('daily_report_enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('daily_report_time', sa.String(5), nullable=False, server_default='18:00'),
        sa.Column('issue_notification_enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('fuel_alert_threshold', sa.Float(), nullable=True),
        sa.Column('link_expiry_hours', sa.Integer(), nullable=False, server_default='24'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            'link_expiry_hours > 0 AND link_expiry_hours <= 168',
            name='valid_expiry_hours',
        ),
    )


def downgrade() -> None:
    op.drop_table('owner_settings')
    op.drop_index('idx_activity_logs_user_date', table_name='activity_logs')
    op.drop_table('activity_logs')
    op.drop_index('idx_issue_reports_status_date', table_name='issue_reports')
    op.drop_table('issue_reports')
    op.drop_index('idx_hours_logs_date_machine', table_name='hours_logs')
    op.drop_table('hours_logs')
    op.drop_index('idx_fuel_logs_date_machine', table_name='fuel_logs')
    op.drop_table('fuel_logs')
    op.drop_index('idx_active_assignments', table_name='machine_assignments')
    op.drop_table('machine_assignments')
    op.drop_table('machines')
    op.drop_table('users')
