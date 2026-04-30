"""Rename users.telegram_id to platform_user_id

Revision ID: 003_rename_telegram_id
Revises: 002_vfm_agency_tables
Create Date: 2026-04-29
"""

from alembic import op

revision = "003_rename_telegram_id"
down_revision = "002_vfm_agency_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("users", "telegram_id", new_column_name="platform_user_id")
    op.drop_constraint("unique_telegram_per_owner", "users", type_="unique")
    op.create_unique_constraint(
        "unique_platform_user_per_owner", "users", ["platform_user_id", "owner_id"]
    )


def downgrade() -> None:
    op.drop_constraint("unique_platform_user_per_owner", "users", type_="unique")
    op.create_unique_constraint(
        "unique_telegram_per_owner", "users", ["telegram_id", "owner_id"]
    )
    op.alter_column("users", "platform_user_id", new_column_name="telegram_id")
