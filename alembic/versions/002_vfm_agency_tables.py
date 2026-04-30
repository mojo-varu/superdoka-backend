"""Add VFM agency tables and harden group_messages

Revision ID: 002_vfm_agency_tables
Revises: (your existing latest revision)
Create Date: 2026-03-26

What this migration does (ALL ADDITIVE — zero existing columns removed):
  1. group_messages:  +source, +retry_count, +last_error, +failed_at,
                      +timeline_event_id, +idx on (status, retry_count)
  2. fuel_logs:       +timeline_event_id FK
  3. hours_logs:      +timeline_event_id FK
  4. issue_reports:   +timeline_event_id FK
  5. owner_settings:  +morning_nudge_enabled, +morning_nudge_time, +checkin_interval_hours
  6. NEW TABLE: timeline_events
  7. NEW TABLE: machine_states
  8. NEW TABLE: active_sessions
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Alembic identifiers
revision = "002_vfm_agency_tables"
down_revision = "001_add_group_tables"
branch_labels = None
depends_on    = None


def upgrade() -> None:

    # ------------------------------------------------------------------ #
    # 1. NEW TABLE: timeline_events                                        #
    # Must be created before tables that FK into it.                      #
    # ------------------------------------------------------------------ #
    op.create_table(
        "timeline_events",
        sa.Column("id",         sa.Integer(), primary_key=True, index=True),
        sa.Column("machine_id", sa.Integer(), sa.ForeignKey("machines.id"), nullable=False),
        sa.Column("operator_id",sa.Integer(), sa.ForeignKey("users.id"),    nullable=True),
        sa.Column("event_type", sa.String(50),  nullable=False),
        sa.Column("content",    sa.JSON(),       nullable=False, server_default="{}"),
        sa.Column("raw_text",   sa.Text(),       nullable=True),
        sa.Column("source",     sa.String(20),   nullable=False, server_default="telegram"),
        sa.Column("confidence", sa.Float(),      nullable=True),
        sa.Column("via_llm",    sa.Boolean(),    nullable=False, server_default="false"),
        sa.Column("corrected_event_id", sa.Integer(),
                  sa.ForeignKey("timeline_events.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint(
            "event_type IN ("
            "'SHIFT_START','SHIFT_END','FUEL_LOG','HOURS_LOG','ISSUE_REPORT',"
            "'STATUS_UPDATE','PRODUCTION_LOG','INSPECTION_CHECK','PARTS_REQUEST',"
            "'HANDOVER_NOTE','MACHINE_SWITCH','CORRECTION','WATCHER_ALERT'"
            ")",
            name="valid_event_type",
        ),
    )
    op.create_index("idx_timeline_machine_type_date",
                    "timeline_events", ["machine_id", "event_type", "created_at"])
    op.create_index("idx_timeline_operator_date",
                    "timeline_events", ["operator_id", "created_at"])

    # ------------------------------------------------------------------ #
    # 2. NEW TABLE: machine_states                                         #
    # ------------------------------------------------------------------ #
    op.create_table(
        "machine_states",
        sa.Column("machine_id",          sa.Integer(),
                  sa.ForeignKey("machines.id"), primary_key=True),
        sa.Column("status",              sa.String(20),  nullable=False,
                  server_default="IDLE"),
        sa.Column("active_operator_id",  sa.Integer(),
                  sa.ForeignKey("users.id"), nullable=True),
        sa.Column("last_known_fuel_liters", sa.Float(), nullable=True),
        sa.Column("last_known_hours",       sa.Float(), nullable=True),
        sa.Column("fuel_added_today",       sa.Float(), nullable=False, server_default="0"),
        sa.Column("hours_worked_today",     sa.Float(), nullable=False, server_default="0"),
        sa.Column("open_issue_count",       sa.Integer(), nullable=False, server_default="0"),
        sa.Column("shift_started_at",    sa.DateTime(), nullable=True),
        sa.Column("last_event_at",       sa.DateTime(), nullable=True),
        sa.Column("updated_at",          sa.DateTime(), nullable=False,
                  server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('IDLE','ASSIGNED','WORKING','WARNING','DOWN','MAINTENANCE')",
            name="valid_machine_status",
        ),
    )
    op.create_index("idx_machine_states_status", "machine_states", ["status"])

    # ------------------------------------------------------------------ #
    # 3. NEW TABLE: active_sessions                                        #
    # ------------------------------------------------------------------ #
    op.create_table(
        "active_sessions",
        sa.Column("operator_id", sa.Integer(),
                  sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("machine_id",  sa.Integer(),
                  sa.ForeignKey("machines.id"), nullable=False),
        sa.Column("shift_state", sa.String(10), nullable=False, server_default="ACTIVE"),
        sa.Column("started_at",  sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at",sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("expected_end",sa.DateTime(), nullable=True),
        sa.Column("fuel_logged_this_shift",  sa.Float(), nullable=False, server_default="0"),
        sa.Column("hours_logged_this_shift", sa.Float(), nullable=False, server_default="0"),
        sa.Column("checkin_count",           sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint(
            "shift_state IN ('IDLE','ACTIVE','ENDED')",
            name="valid_shift_state",
        ),
    )
    op.create_index("idx_active_sessions_machine", "active_sessions", ["machine_id"])
    op.create_index("idx_active_sessions_state",   "active_sessions", ["shift_state"])

    # ------------------------------------------------------------------ #
    # 4. ALTER: group_messages — add failure-handling + source columns     #
    # ------------------------------------------------------------------ #
    op.add_column("group_messages",
        sa.Column("source", sa.String(20), nullable=False, server_default="telegram"))
    op.add_column("group_messages",
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("group_messages",
        sa.Column("last_error", sa.Text(), nullable=True))
    op.add_column("group_messages",
        sa.Column("failed_at", sa.DateTime(), nullable=True))
    op.add_column("group_messages",
        sa.Column("timeline_event_id", sa.Integer(),
                  sa.ForeignKey("timeline_events.id"), nullable=True))
    op.create_index("idx_group_messages_status_retry",
                    "group_messages", ["processing_status", "retry_count"])

    # ------------------------------------------------------------------ #
    # 5. ALTER: fuel_logs / hours_logs / issue_reports — add timeline FK  #
    # ------------------------------------------------------------------ #
    for table in ("fuel_logs", "hours_logs", "issue_reports"):
        op.add_column(table,
            sa.Column("timeline_event_id", sa.Integer(),
                      sa.ForeignKey("timeline_events.id"), nullable=True))

    # ------------------------------------------------------------------ #
    # 6. ALTER: owner_settings — add watcher nudge preferences            #
    # ------------------------------------------------------------------ #
    op.add_column("owner_settings",
        sa.Column("morning_nudge_enabled",  sa.Boolean(), nullable=False, server_default="true"))
    op.add_column("owner_settings",
        sa.Column("morning_nudge_time",     sa.String(5), nullable=False, server_default="07:30"))
    op.add_column("owner_settings",
        sa.Column("checkin_interval_hours", sa.Integer(), nullable=False, server_default="4"))


def downgrade() -> None:
    # Reverse in opposite order to respect FK dependencies

    # owner_settings additions
    for col in ("morning_nudge_enabled", "morning_nudge_time", "checkin_interval_hours"):
        op.drop_column("owner_settings", col)

    # timeline FK columns on log tables
    for table in ("fuel_logs", "hours_logs", "issue_reports"):
        op.drop_column(table, "timeline_event_id")

    # group_messages additions
    op.drop_index("idx_group_messages_status_retry", table_name="group_messages")
    for col in ("source", "retry_count", "last_error", "failed_at", "timeline_event_id"):
        op.drop_column("group_messages", col)

    # New tables (reverse creation order)
    op.drop_index("idx_active_sessions_state",   table_name="active_sessions")
    op.drop_index("idx_active_sessions_machine", table_name="active_sessions")
    op.drop_table("active_sessions")

    op.drop_index("idx_machine_states_status", table_name="machine_states")
    op.drop_table("machine_states")

    op.drop_index("idx_timeline_operator_date",     table_name="timeline_events")
    op.drop_index("idx_timeline_machine_type_date", table_name="timeline_events")
    op.drop_table("timeline_events")
