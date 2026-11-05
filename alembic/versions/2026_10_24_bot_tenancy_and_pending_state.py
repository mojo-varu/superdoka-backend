"""WP-B: org tenancy, bot intake idempotency, pending-confirmation/chat-state/
invite/channel-notice tables, consent + reachability columns.

Reversible. Targets a disposable local database for review — NOT run against
any real database by this task (see CLAUDE_CODE_BOT_BUILD_PROMPT.md ground
rules). batch_alter_table is used throughout for SQLite compatibility
(the local dev fallback per CLAUDE.md), and is a no-op wrapper on Postgres.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-10-24
"""
from __future__ import annotations

from datetime import datetime
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_ORG_ID = 1


def upgrade() -> None:
    # ---- orgs ---------------------------------------------------------
    op.create_table(
        "orgs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="Europe/Moscow"),
        sa.Column("digest_time", sa.String(5), nullable=False, server_default="18:00"),
        sa.Column("quiet_hours_start", sa.String(5), nullable=False, server_default="21:00"),
        sa.Column("quiet_hours_end", sa.String(5), nullable=False, server_default="06:00"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.bulk_insert(
        sa.table(
            "orgs",
            sa.column("id", sa.Integer()),
            sa.column("name", sa.String()),
            sa.column("created_at", sa.DateTime()),
        ),
        [{"id": DEFAULT_ORG_ID, "name": "Default Org", "created_at": datetime.utcnow()}],
    )

    # ---- org_id on existing tables ------------------------------------
    for table in ("users", "machines", "conversation_log"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(
                sa.Column("org_id", sa.Integer(), nullable=False, server_default=str(DEFAULT_ORG_ID))
            )
            batch.create_foreign_key(f"fk_{table}_org", "orgs", ["org_id"], ["id"])

    # ---- users: consent + reachability ---------------------------------
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("consent_given_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("consent_version", sa.String(20), nullable=True))
        batch.add_column(sa.Column("is_reachable", sa.Boolean(), nullable=False, server_default="true"))

    # ---- conversation_log: intake/idempotency columns -------------------
    with op.batch_alter_table("conversation_log") as batch:
        batch.alter_column("operator_id", nullable=True)
        batch.alter_column("raw_text", nullable=True)
        batch.add_column(sa.Column("channel", sa.String(20), nullable=True))
        batch.add_column(sa.Column("chat_id", sa.String(64), nullable=True))
        batch.add_column(sa.Column("update_id", sa.String(64), nullable=True))
        batch.add_column(sa.Column("processing_status", sa.String(20), nullable=False, server_default="received"))
        batch.add_column(sa.Column("claimed_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("correlation_id", sa.String(64), nullable=True))
        batch.add_column(sa.Column("media_file_unique_id", sa.String(128), nullable=True))
        batch.add_column(sa.Column("raw_update", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("timeline_event_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("corrected_by", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_conv_log_timeline_event", "timeline_events", ["timeline_event_id"], ["id"])
        batch.create_foreign_key("fk_conv_log_corrected_by", "timeline_events", ["corrected_by"], ["id"])
        batch.create_unique_constraint("uq_conv_log_channel_update_id", ["channel", "update_id"])
    op.create_index("idx_conv_log_chat_id", "conversation_log", ["chat_id"])
    op.create_index("idx_conv_log_correlation", "conversation_log", ["correlation_id"])
    op.create_index("idx_conv_log_status", "conversation_log", ["processing_status", "claimed_at"])

    # ---- invites --------------------------------------------------------
    op.create_table(
        "invites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("org_id", sa.Integer(), sa.ForeignKey("orgs.id"), nullable=False, server_default=str(DEFAULT_ORG_ID)),
        sa.Column("token", sa.String(64), nullable=False, unique=True),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("operator_name", sa.String(100), nullable=True),
        sa.Column("machine_id", sa.Integer(), sa.ForeignKey("machines.id"), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("used_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_invites_token", "invites", ["token"])

    # ---- pending_confirmations -------------------------------------------
    op.create_table(
        "pending_confirmations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("org_id", sa.Integer(), sa.ForeignKey("orgs.id"), nullable=False, server_default=str(DEFAULT_ORG_ID)),
        sa.Column("operator_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("machine_id", sa.Integer(), sa.ForeignKey("machines.id"), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("source_conversation_id", sa.Integer(), sa.ForeignKey("conversation_log.id"), nullable=True),
        sa.Column("proposed_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_event_id", sa.Integer(), sa.ForeignKey("timeline_events.id"), nullable=True),
    )
    op.create_index("idx_pending_conf_unresolved", "pending_confirmations", ["operator_id", "resolved_at"])
    op.create_index("idx_pending_conf_expires", "pending_confirmations", ["expires_at"])

    # ---- chat_states -------------------------------------------------------
    op.create_table(
        "chat_states",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("org_id", sa.Integer(), sa.ForeignKey("orgs.id"), nullable=False, server_default=str(DEFAULT_ORG_ID)),
        sa.Column("chat_id", sa.String(64), nullable=False),
        sa.Column("state_key", sa.String(50), nullable=False),
        sa.Column("state_payload", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("chat_id", "state_key", name="uq_chat_state_chat_key"),
    )

    # ---- channel_notices ----------------------------------------------------
    op.create_table(
        "channel_notices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("chat_id", sa.String(64), nullable=False),
        sa.Column("notice_key", sa.String(50), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("channel", "chat_id", "notice_key", name="uq_channel_notice"),
    )


def downgrade() -> None:
    op.drop_table("channel_notices")
    op.drop_table("chat_states")
    op.drop_table("pending_confirmations")
    op.drop_table("invites")

    op.drop_index("idx_conv_log_status", table_name="conversation_log")
    op.drop_index("idx_conv_log_correlation", table_name="conversation_log")
    op.drop_index("idx_conv_log_chat_id", table_name="conversation_log")
    with op.batch_alter_table("conversation_log") as batch:
        batch.drop_constraint("uq_conv_log_channel_update_id", type_="unique")
        batch.drop_constraint("fk_conv_log_corrected_by", type_="foreignkey")
        batch.drop_constraint("fk_conv_log_timeline_event", type_="foreignkey")
        batch.drop_column("corrected_by")
        batch.drop_column("timeline_event_id")
        batch.drop_column("raw_update")
        batch.drop_column("media_file_unique_id")
        batch.drop_column("correlation_id")
        batch.drop_column("claimed_at")
        batch.drop_column("processing_status")
        batch.drop_column("update_id")
        batch.drop_column("chat_id")
        batch.drop_column("channel")
        batch.alter_column("raw_text", nullable=False)
        batch.alter_column("operator_id", nullable=False)

    with op.batch_alter_table("users") as batch:
        batch.drop_column("is_reachable")
        batch.drop_column("consent_version")
        batch.drop_column("consent_given_at")

    for table in ("conversation_log", "machines", "users"):
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(f"fk_{table}_org", type_="foreignkey")
            batch.drop_column("org_id")

    op.drop_table("orgs")
