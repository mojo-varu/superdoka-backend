"""SPEC-001-R05/R06/R13: Invite.bound_user_id; retire the old
MachineAssignment telegram_link_* onboarding mechanism.

Context (see docs/proposals/AMENDMENTS.md "Invite vs. the existing
MachineAssignment link-token fields" for the full history): this repo had
two parallel Telegram-invite mechanisms — the old MachineAssignment
telegram_link_token/_expires_at/_used_at columns plus
MachineOperatorLinkGenerator in app/api/v1/endpoints/owners.py (hardcoded
bot username, a link format the real bot's /start parser never understood),
and the Invite table used by the actual bot's /start handler
(app/services/onboarding_service.bind_invite). Confirmed nothing in the
sandbox depends on the old mechanism — this migration retires it.

bound_user_id lets an owner pre-create the operator's User row before
issuing the invite; redemption then attaches platform_user_id to that row
instead of creating a duplicate one (app/services/fleet_admin_service.py,
app/services/onboarding_service.bind_invite).

Reversible. batch_alter_table is used throughout for SQLite compatibility,
matching alembic/versions/2026_10_24_bot_tenancy_and_pending_state.py.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-11-05
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("invites") as batch:
        batch.add_column(sa.Column("bound_user_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_invites_bound_user", "users", ["bound_user_id"], ["id"])

    # telegram_link_token was created inline (unique=True, index=True) in
    # 000_initial_tables.py, giving it SQLAlchemy's default auto-index name
    # (matches this repo's convention — see ix_machines_alias in
    # 004_add_machine_alias.py).
    with op.batch_alter_table("machine_assignments") as batch:
        batch.drop_index("ix_machine_assignments_telegram_link_token")
        batch.drop_column("telegram_link_token")
        batch.drop_column("telegram_link_expires_at")
        batch.drop_column("telegram_link_used_at")


def downgrade() -> None:
    with op.batch_alter_table("machine_assignments") as batch:
        batch.add_column(sa.Column("telegram_link_token", sa.String(100), nullable=True))
        batch.add_column(sa.Column("telegram_link_expires_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("telegram_link_used_at", sa.DateTime(), nullable=True))
    op.create_index(
        "ix_machine_assignments_telegram_link_token",
        "machine_assignments",
        ["telegram_link_token"],
        unique=True,
    )

    with op.batch_alter_table("invites") as batch:
        batch.drop_constraint("fk_invites_bound_user", type_="foreignkey")
        batch.drop_column("bound_user_id")
