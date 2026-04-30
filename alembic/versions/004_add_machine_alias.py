"""Add machines.alias column

Revision ID: 004_add_machine_alias
Revises: 003_rename_telegram_id
Create Date: 2026-04-29

alias is the human-friendly callsign operators use in messages ("КАТ-101",
"Комацу"). reg_number remains the immutable real-world identity (GOST plate).
The column is nullable so existing rows are unaffected; the application
auto-derives a value for any row that still has NULL.
"""

from alembic import op
import sqlalchemy as sa

revision = "004_add_machine_alias"
down_revision = "003_rename_telegram_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("machines", sa.Column("alias", sa.String(50), nullable=True))
    op.create_index("ix_machines_alias", "machines", ["alias"])


def downgrade() -> None:
    op.drop_index("ix_machines_alias", table_name="machines")
    op.drop_column("machines", "alias")
