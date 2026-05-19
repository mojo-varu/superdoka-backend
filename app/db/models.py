"""
app/db/models.py

Hour 1 changes:
  - UserType enum preserved exactly as-is (fixes UserTypeEnum bug at usage site)
  - GroupMessage: +retry_count, +last_error, +failed_at, +source, status enum extended
  - NEW: MachineState   — live digital twin snapshot per machine
  - NEW: TimelineEvent  — immutable event ledger (PdM foundation)
  - NEW: ActiveSession  — current shift binding (Agency unlock)

All changes are ADDITIVE. Zero existing columns removed or renamed.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Column, DateTime,
    Float, ForeignKey, Index, Integer, JSON, String, Text,
    UniqueConstraint,
)
from sqlalchemy import event as sa_event
from sqlalchemy.orm import Mapped, relationship

from app.db.base import Base


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class UserType(enum.Enum):
    OWNER    = "OWNER"
    OPERATOR = "OPERATOR"


class LogIntent(enum.Enum):
    FUEL_LOG     = "fuel_log"
    HOURS_LOG    = "hours_log"
    REPORT_ISSUE = "report_issue"


class IssueStatus(enum.Enum):
    REPORTED    = "REPORTED"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED    = "RESOLVED"
    CLOSED      = "CLOSED"


class IssuePriority(enum.Enum):
    LOW      = "LOW"
    MEDIUM   = "MEDIUM"
    HIGH     = "HIGH"
    CRITICAL = "CRITICAL"


# NEW — machine lifecycle states
class MachineStatus(enum.Enum):
    IDLE        = "IDLE"
    ASSIGNED    = "ASSIGNED"
    WORKING     = "WORKING"
    WARNING     = "WARNING"
    DOWN        = "DOWN"
    MAINTENANCE = "MAINTENANCE"


# NEW — shift lifecycle states
class ShiftState(enum.Enum):
    IDLE   = "IDLE"
    ACTIVE = "ACTIVE"
    ENDED  = "ENDED"


# NEW — event types written to the timeline ledger
class EventType(enum.Enum):
    SHIFT_START       = "SHIFT_START"
    SHIFT_END         = "SHIFT_END"
    FUEL_LOG          = "FUEL_LOG"
    HOURS_LOG         = "HOURS_LOG"
    ISSUE_REPORT      = "ISSUE_REPORT"
    STATUS_UPDATE     = "STATUS_UPDATE"
    PRODUCTION_LOG    = "PRODUCTION_LOG"
    INSPECTION_CHECK  = "INSPECTION_CHECK"
    PARTS_REQUEST     = "PARTS_REQUEST"
    HANDOVER_NOTE     = "HANDOVER_NOTE"
    MACHINE_SWITCH    = "MACHINE_SWITCH"
    CORRECTION        = "CORRECTION"
    WATCHER_ALERT     = "WATCHER_ALERT"


# NEW — message processing pipeline statuses
class ProcessingStatus(enum.Enum):
    PENDING    = "pending"
    PROCESSING = "processing"
    PROCESSED  = "processed"
    FAILED     = "failed"


# NEW — inbound message source adapter
class MessageSource(enum.Enum):
    TELEGRAM = "telegram"
    MAX      = "max"
    REST     = "rest"


# ---------------------------------------------------------------------------
# Existing models (unchanged except documented)
# ---------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id           = Column(Integer, primary_key=True, index=True)
    platform_user_id = Column(BigInteger, nullable=True, index=True)
    mobile       = Column(String(20), nullable=False, index=True)
    name         = Column(String(100), nullable=False)
    company_name = Column(String(100), nullable=True)
    user_type    = Column(String(20), nullable=False)   # "OWNER" | "OPERATOR"
    owner_id     = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    is_active    = Column(Boolean, default=True, nullable=False)
    created_at   = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at   = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    owner            = relationship("User", remote_side="User.id", backref="operators")
    owned_machines:  Mapped[List["Machine"]]          = relationship("Machine", back_populates="owner")
    assigned_machines: Mapped[List["MachineAssignment"]] = relationship("MachineAssignment", back_populates="operator")
    fuel_logs:       Mapped[List["FuelLog"]]          = relationship("FuelLog", back_populates="operator")
    hours_logs:      Mapped[List["HoursLog"]]         = relationship("HoursLog", back_populates="operator")
    issue_reports:   Mapped[List["IssueReport"]]      = relationship("IssueReport", back_populates="operator")
    # NEW relationships
    active_session:  Mapped[Optional["ActiveSession"]] = relationship("ActiveSession", back_populates="operator", uselist=False)
    timeline_events: Mapped[List["TimelineEvent"]]    = relationship("TimelineEvent", back_populates="operator", foreign_keys="TimelineEvent.operator_id")

    __table_args__ = (
        CheckConstraint("user_type IN ('OWNER', 'OPERATOR')", name="valid_user_type"),
        CheckConstraint(
            "(user_type = 'OWNER' AND owner_id IS NULL) OR "
            "(user_type = 'OPERATOR' AND owner_id IS NOT NULL)",
            name="owner_relationship_constraint",
        ),
        UniqueConstraint("platform_user_id", "owner_id", name="unique_platform_user_per_owner"),
        {"extend_existing": True},
    )


class Machine(Base):
    __tablename__ = "machines"

    id           = Column(Integer, primary_key=True, index=True)
    reg_number   = Column(String(20), nullable=False, unique=True, index=True)
    alias        = Column(String(50), nullable=True, index=True)   # human-friendly callsign, auto-derived if not supplied
    machine_type = Column(String(100), nullable=False, index=True)
    model        = Column(String(100), nullable=False)
    year         = Column(Integer, nullable=False)
    owner_id     = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    is_active    = Column(Boolean, default=True, nullable=False)
    created_at   = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at   = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    serial_number = Column(String(100), nullable=True)
    purchase_date = Column(DateTime, nullable=True)
    notes         = Column(Text, nullable=True)

    owner       = relationship("User", back_populates="owned_machines")
    assignments: Mapped[List["MachineAssignment"]] = relationship("MachineAssignment", back_populates="machine")
    fuel_logs:  Mapped[List["FuelLog"]]   = relationship("FuelLog", back_populates="machine")
    hours_logs: Mapped[List["HoursLog"]]  = relationship("HoursLog", back_populates="machine")
    issue_reports: Mapped[List["IssueReport"]] = relationship("IssueReport", back_populates="machine")
    # NEW relationships
    state:           Mapped[Optional["MachineState"]]  = relationship("MachineState", back_populates="machine", uselist=False)
    timeline_events: Mapped[List["TimelineEvent"]]     = relationship("TimelineEvent", back_populates="machine")
    active_sessions: Mapped[List["ActiveSession"]]     = relationship("ActiveSession", back_populates="machine")

    __table_args__ = (
        CheckConstraint("year >= 1900 AND year <= 2030", name="valid_year"),
        {"extend_existing": True},
    )


@sa_event.listens_for(Machine, "before_insert")
@sa_event.listens_for(Machine, "before_update")
def normalise_machine_reg(mapper, connection, target):
    from app.core.text_normaliser import normalise_plate
    if target.reg_number:
        target.reg_number = normalise_plate(target.reg_number)


class MachineAssignment(Base):
    __tablename__ = "machine_assignments"

    id              = Column(Integer, primary_key=True, index=True)
    machine_id      = Column(Integer, ForeignKey("machines.id"), nullable=False, index=True)
    operator_id     = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    assigned_at     = Column(DateTime, default=datetime.utcnow, nullable=False)
    unassigned_at   = Column(DateTime, nullable=True)
    is_active       = Column(Boolean, default=True, nullable=False)

    telegram_link_token      = Column(String(100), nullable=True, unique=True, index=True)
    telegram_link_expires_at = Column(DateTime, nullable=True)
    telegram_link_used_at    = Column(DateTime, nullable=True)

    machine  = relationship("Machine", back_populates="assignments")
    operator = relationship("User", back_populates="assigned_machines")

    __table_args__ = (
        UniqueConstraint("operator_id", "machine_id", name="uq_assignment_operator_machine"),
        Index("idx_active_assignments", "machine_id", "is_active"),
        {"extend_existing": True},
    )


class FuelLog(Base):
    __tablename__ = "fuel_logs"

    id          = Column(Integer, primary_key=True, index=True)
    machine_id  = Column(Integer, ForeignKey("machines.id"), nullable=False, index=True)
    operator_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    fuel_volume = Column(Float, nullable=False)
    unit        = Column(String(20), default="литров", nullable=False)

    telegram_message_id = Column(BigInteger, nullable=True)
    original_text       = Column(Text, nullable=False)
    parsed_data         = Column(Text, nullable=True)

    # NEW: link back to the timeline event that created this log
    timeline_event_id = Column(Integer, ForeignKey("timeline_events.id"), nullable=True, index=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    machine  = relationship("Machine", back_populates="fuel_logs")
    operator = relationship("User", back_populates="fuel_logs")

    __table_args__ = (
        CheckConstraint("fuel_volume > 0", name="positive_fuel_volume"),
        Index("idx_fuel_logs_date_machine", "created_at", "machine_id"),
        {"extend_existing": True},
    )


class HoursLog(Base):
    __tablename__ = "hours_logs"

    id          = Column(Integer, primary_key=True, index=True)
    machine_id  = Column(Integer, ForeignKey("machines.id"), nullable=False, index=True)
    operator_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    hours       = Column(Float, nullable=False)
    unit        = Column(String(20), default="часов", nullable=False)

    telegram_message_id = Column(BigInteger, nullable=True)
    original_text       = Column(Text, nullable=False)
    parsed_data         = Column(Text, nullable=True)

    # NEW: link back to the timeline event
    timeline_event_id = Column(Integer, ForeignKey("timeline_events.id"), nullable=True, index=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    machine  = relationship("Machine", back_populates="hours_logs")
    operator = relationship("User", back_populates="hours_logs")

    __table_args__ = (
        CheckConstraint("hours > 0", name="positive_hours"),
        Index("idx_hours_logs_date_machine", "created_at", "machine_id"),
        {"extend_existing": True},
    )


class IssueReport(Base):
    __tablename__ = "issue_reports"

    id          = Column(Integer, primary_key=True, index=True)
    machine_id  = Column(Integer, ForeignKey("machines.id"), nullable=False, index=True)
    operator_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    description = Column(Text, nullable=False)
    status      = Column(String(20), default="REPORTED", nullable=False)
    priority    = Column(String(20), default="MEDIUM", nullable=False)

    telegram_message_id = Column(BigInteger, nullable=True)
    original_text       = Column(Text, nullable=False)
    parsed_data         = Column(Text, nullable=True)

    resolved_at       = Column(DateTime, nullable=True)
    resolution_notes  = Column(Text, nullable=True)

    # NEW: link back to the timeline event
    timeline_event_id = Column(Integer, ForeignKey("timeline_events.id"), nullable=True, index=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    machine  = relationship("Machine", back_populates="issue_reports")
    operator = relationship("User", back_populates="issue_reports")

    __table_args__ = (
        CheckConstraint(
            "status IN ('REPORTED', 'IN_PROGRESS', 'RESOLVED', 'CLOSED')",
            name="valid_issue_status",
        ),
        CheckConstraint(
            "priority IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')",
            name="valid_issue_priority",
        ),
        Index("idx_issue_reports_status_date", "status", "created_at"),
        {"extend_existing": True},
    )


class ActivityLog(Base):
    __tablename__ = "activity_logs"

    id                  = Column(Integer, primary_key=True, index=True)
    user_id             = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    action              = Column(String(100), nullable=False)
    entity_type         = Column(String(50), nullable=False)
    entity_id           = Column(Integer, nullable=False)
    details             = Column(Text, nullable=True)
    telegram_message_id = Column(BigInteger, nullable=True)
    created_at          = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    user = relationship("User")

    __table_args__ = (
        Index("idx_activity_logs_user_date", "user_id", "created_at"),
        {"extend_existing": True},
    )


class OwnerSettings(Base):
    __tablename__ = "owner_settings"

    id       = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)

    daily_report_enabled        = Column(Boolean, default=True, nullable=False)
    daily_report_time           = Column(String(5), default="18:00", nullable=False)
    issue_notification_enabled  = Column(Boolean, default=True, nullable=False)
    fuel_alert_threshold        = Column(Float, nullable=True)
    link_expiry_hours           = Column(Integer, default=24, nullable=False)

    # NEW: watcher nudge preferences
    morning_nudge_enabled  = Column(Boolean, default=True, nullable=False)
    morning_nudge_time     = Column(String(5), default="07:30", nullable=False)
    checkin_interval_hours = Column(Integer, default=4, nullable=False)  # nudge if no checkin

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    owner = relationship("User")

    __table_args__ = (
        CheckConstraint(
            "link_expiry_hours > 0 AND link_expiry_hours <= 168",
            name="valid_expiry_hours",
        ),
        {"extend_existing": True},
    )


class Group(Base):
    __tablename__ = "groups"

    id         = Column(Integer, primary_key=True, index=True)
    group_id   = Column(BigInteger, nullable=False, unique=True, index=True)
    group_name = Column(String(255), nullable=False)
    owner_id   = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    is_active  = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    owner    = relationship("User")
    messages: Mapped[List["GroupMessage"]] = relationship("GroupMessage", back_populates="group")

    __table_args__ = (
        Index("idx_groups_owner", "owner_id"),
        {"extend_existing": True},
    )


class GroupMessage(Base):
    """
    Inbound message queue.

    Hour 1 additions:
      source       — which adapter delivered this (telegram | max | rest)
      retry_count  — how many times the worker has attempted processing
      last_error   — last exception string for debugging
      failed_at    — timestamp when message moved to 'failed' state
    """
    __tablename__ = "group_messages"

    id         = Column(Integer, primary_key=True, index=True)
    group_id   = Column(Integer, ForeignKey("groups.id"), nullable=False, index=True)
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    telegram_user_id    = Column(BigInteger, nullable=False, index=True)
    username            = Column(String(100), nullable=True)
    first_name          = Column(String(100), nullable=True)
    last_name           = Column(String(100), nullable=True)
    telegram_message_id = Column(BigInteger, nullable=False, unique=True, index=True)

    message_text = Column(Text, nullable=False)
    message_type = Column(String(50), nullable=False)

    reply_to_message_id = Column(BigInteger, nullable=True)
    original_sender     = Column(String(255), nullable=True)

    parsed_data = Column(Text, nullable=True)

    # Extended processing pipeline
    processing_status = Column(
        String(50), default=ProcessingStatus.PENDING.value, nullable=False
    )
    # NEW columns — failure handling
    source      = Column(String(20), default=MessageSource.TELEGRAM.value, nullable=False)
    retry_count = Column(Integer, default=0, nullable=False)
    last_error  = Column(Text, nullable=True)
    failed_at   = Column(DateTime, nullable=True)

    # NEW: link to the timeline event created from this message
    timeline_event_id = Column(Integer, ForeignKey("timeline_events.id"), nullable=True, index=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    group = relationship("Group", back_populates="messages")
    user  = relationship("User")

    __table_args__ = (
        Index("idx_group_messages_date_group", "created_at", "group_id"),
        Index("idx_group_messages_user_date", "telegram_user_id", "created_at"),
        # NEW: index for the worker queue drain query
        Index("idx_group_messages_status_retry", "processing_status", "retry_count"),
        {"extend_existing": True},
    )


# ---------------------------------------------------------------------------
# NEW MODEL 1: MachineState — the digital twin live snapshot
# ---------------------------------------------------------------------------

class MachineState(Base):
    """
    One row per machine. UPSERT on every relevant TimelineEvent.
    Allows instant "what is this machine doing right now?" queries
    without aggregating thousands of log rows.
    """
    __tablename__ = "machine_states"

    machine_id = Column(
        Integer, ForeignKey("machines.id"), primary_key=True, index=True
    )

    status = Column(
        String(20),
        default=MachineStatus.IDLE.value,
        nullable=False,
    )

    active_operator_id = Column(
        Integer, ForeignKey("users.id"), nullable=True, index=True
    )

    # Last-known readings (updated on each relevant event)
    last_known_fuel_liters = Column(Float, nullable=True)
    last_known_hours       = Column(Float, nullable=True)
    fuel_added_today       = Column(Float, default=0.0, nullable=False)
    hours_worked_today     = Column(Float, default=0.0, nullable=False)

    # Open issue count — denormalised for fast rule evaluation
    open_issue_count = Column(Integer, default=0, nullable=False)

    # Timestamps
    shift_started_at = Column(DateTime, nullable=True)
    last_event_at    = Column(DateTime, nullable=True)
    updated_at       = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    machine         = relationship("Machine", back_populates="state")
    active_operator = relationship("User", foreign_keys=[active_operator_id])

    __table_args__ = (
        CheckConstraint(
            "status IN ('IDLE','ASSIGNED','WORKING','WARNING','DOWN','MAINTENANCE')",
            name="valid_machine_status",
        ),
        Index("idx_machine_states_status", "status"),
        {"extend_existing": True},
    )


# ---------------------------------------------------------------------------
# NEW MODEL 2: TimelineEvent — immutable event ledger (PdM foundation)
# ---------------------------------------------------------------------------

class TimelineEvent(Base):
    """
    Append-only ledger. Every operator action creates one row.
    This is the raw material for anomaly detection, pattern recognition,
    and predictive maintenance — built passively from day one.

    content JSONB holds event-type-specific structured data:
      FUEL_LOG:     {liters: 50, unit: "л", is_delta: true}
      HOURS_LOG:    {hours: 8.5, reading_type: "delta|absolute"}
      ISSUE_REPORT: {component: "hydraulics", symptom: "leak", severity: "HIGH"}
      SHIFT_START:  {expected_end: "18:00", machine_id: 101}
      CORRECTION:   {original_event_id: 42, field: "fuel_volume", old: 50, new: 55}
    """
    __tablename__ = "timeline_events"

    id          = Column(Integer, primary_key=True, index=True)
    machine_id  = Column(Integer, ForeignKey("machines.id"), nullable=False, index=True)
    operator_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    event_type = Column(String(50), nullable=False, index=True)
    content    = Column(JSON, nullable=False, default=dict)
    raw_text   = Column(Text, nullable=True)

    # Intelligence metadata
    source     = Column(String(20), default=MessageSource.TELEGRAM.value, nullable=False)
    confidence = Column(Float, nullable=True)   # NER confidence 0.0–1.0
    via_llm    = Column(Boolean, default=False, nullable=False)  # True if LLM fallback used

    # Correction chain — if this event corrects an earlier one
    corrected_event_id = Column(
        Integer, ForeignKey("timeline_events.id"), nullable=True, index=True
    )

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Relationships
    machine  = relationship("Machine", back_populates="timeline_events")
    operator = relationship("User", back_populates="timeline_events", foreign_keys=[operator_id])
    corrected_event = relationship("TimelineEvent", remote_side="TimelineEvent.id")

    __table_args__ = (
        CheckConstraint(
            "event_type IN ("
            "'SHIFT_START','SHIFT_END','FUEL_LOG','HOURS_LOG','ISSUE_REPORT',"
            "'STATUS_UPDATE','PRODUCTION_LOG','INSPECTION_CHECK','PARTS_REQUEST',"
            "'HANDOVER_NOTE','MACHINE_SWITCH','CORRECTION','WATCHER_ALERT'"
            ")",
            name="valid_event_type",
        ),
        Index("idx_timeline_machine_type_date", "machine_id", "event_type", "created_at"),
        Index("idx_timeline_operator_date", "operator_id", "created_at"),
        {"extend_existing": True},
    )


# ---------------------------------------------------------------------------
# ConversationLog — append-only log of every operator message and VFM reply
# ---------------------------------------------------------------------------

class ConversationLog(Base):
    """
    Append-only log of every operator message and VFM reply.
    This is the primary input for the replay harness.
    Covers all intents — operational and non-operational.
    Never modified after write.
    """
    __tablename__ = "conversation_log"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    operator_id   = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    machine_id    = Column(Integer, ForeignKey("machines.id"), nullable=True)
    raw_text      = Column(Text, nullable=False)
    intent        = Column(String(64), nullable=True)
    confidence    = Column(Float, nullable=True)
    policy_action = Column(String(32), nullable=True)   # CONFIRM | CLARIFY | ALERT | NUDGE | ESCALATE
    task_type     = Column(String(8),  nullable=True)   # T1–T8
    vfm_reply     = Column(Text, nullable=True)
    source        = Column(String(32), nullable=True)
    created_at    = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        Index("idx_conv_log_operator_date", "operator_id", "created_at"),
        {"extend_existing": True},
    )


# ---------------------------------------------------------------------------
# NEW MODEL 3: ActiveSession — current shift binding (the Agency unlock)
# ---------------------------------------------------------------------------

class ActiveSession(Base):
    """
    One row per operator currently on shift.
    Postgres is source of truth. Redis mirrors this for sub-millisecond reads.

    This table answers "Who is on what machine right now?" in O(1).
    Without it, every message requires disambiguation — high friction for operators.

    Lifecycle:
      IDLE   → operator not on shift (no row, or shift_state = IDLE)
      ACTIVE → operator bound to machine, all messages auto-routed
      ENDED  → shift closed, reconciliation triggered
    """
    __tablename__ = "active_sessions"

    # One session per operator at a time
    operator_id = Column(
        Integer, ForeignKey("users.id"), primary_key=True, index=True
    )
    machine_id = Column(
        Integer, ForeignKey("machines.id"), nullable=False, index=True
    )

    shift_state = Column(
        String(10), default=ShiftState.ACTIVE.value, nullable=False
    )

    started_at    = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_seen_at  = Column(DateTime, default=datetime.utcnow, nullable=False)
    expected_end  = Column(DateTime, nullable=True)   # set by owner schedule

    # Running totals for this shift (updated on each event, used by Watcher)
    fuel_logged_this_shift  = Column(Float, default=0.0, nullable=False)
    hours_logged_this_shift = Column(Float, default=0.0, nullable=False)
    checkin_count           = Column(Integer, default=0, nullable=False)

    # Relationships
    operator = relationship("User", back_populates="active_session")
    machine  = relationship("Machine", back_populates="active_sessions")

    __table_args__ = (
        CheckConstraint(
            "shift_state IN ('IDLE','ACTIVE','ENDED')",
            name="valid_shift_state",
        ),
        Index("idx_active_sessions_machine", "machine_id"),
        Index("idx_active_sessions_state", "shift_state"),
        {"extend_existing": True},
    )
