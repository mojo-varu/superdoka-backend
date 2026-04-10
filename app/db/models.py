from sqlalchemy import Column, Integer, String, BigInteger, Boolean, DateTime, Float, Text, ForeignKey, CheckConstraint, UniqueConstraint, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, Mapped
from datetime import datetime
import enum
from typing import List
from app.db.base import Base

class UserType(enum.Enum):
    OWNER = "OWNER"
    OPERATOR = "OPERATOR"

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(BigInteger, nullable=True, index=True)
    mobile = Column(String(20), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    company_name = Column(String(100), nullable=True)
    user_type = Column(String(20), nullable=False)  # OWNER, OPERATOR
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    owner = relationship("User", remote_side="User.id", backref="operators")
    owned_machines: Mapped[List["Machine"]] = relationship("Machine", back_populates="owner")
    assigned_machines: Mapped[List["MachineAssignment"]] = relationship("MachineAssignment", back_populates="operator")
    fuel_logs: Mapped[List["FuelLog"]] = relationship("FuelLog", back_populates="operator")
    hours_logs: Mapped[List["HoursLog"]] = relationship("HoursLog", back_populates="operator")
    issue_reports: Mapped[List["IssueReport"]] = relationship("IssueReport", back_populates="operator")
    
    # Constraints
    __table_args__ = (
        CheckConstraint(
            "user_type IN ('OWNER', 'OPERATOR')",
            name="valid_user_type"
        ),
        CheckConstraint(
            "(user_type = 'OWNER' AND owner_id IS NULL) OR (user_type = 'OPERATOR' AND owner_id IS NOT NULL)",
            name="owner_relationship_constraint"
        ),
        # Unique constraint for telegram_id + owner_id combination
        UniqueConstraint('telegram_id', 'owner_id', name='unique_telegram_per_owner'),
        {"extend_existing": True}
    )

class Machine(Base):
    __tablename__ = "machines"
    
    id = Column(Integer, primary_key=True, index=True)
    reg_number = Column(String(20), nullable=False, unique=True, index=True)  # Primary identifier
    machine_type = Column(String(100), nullable=False, index=True)  # экскаватор, бульдозер, etc.
    model = Column(String(100), nullable=False)  # Caterpillar 320D
    year = Column(Integer, nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Optional fields for future expansion
    serial_number = Column(String(100), nullable=True)
    purchase_date = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)
    
    # Relationships
    owner = relationship("User", back_populates="owned_machines")
    assignments: Mapped[List["MachineAssignment"]] = relationship("MachineAssignment", back_populates="machine")
    fuel_logs: Mapped[List["FuelLog"]] = relationship("FuelLog", back_populates="machine")
    hours_logs: Mapped[List["HoursLog"]] = relationship("HoursLog", back_populates="machine")
    issue_reports: Mapped[List["IssueReport"]] = relationship("IssueReport", back_populates="machine")
    
    __table_args__ = (
        CheckConstraint("year >= 1900 AND year <= 2030", name="valid_year"),
        {"extend_existing": True}
    )

class MachineAssignment(Base):
    __tablename__ = "machine_assignments"
    
    id = Column(Integer, primary_key=True, index=True)
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=False, index=True)
    operator_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    assigned_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    unassigned_at = Column(DateTime, nullable=True)  # NULL means currently assigned
    is_active = Column(Boolean, default=True, nullable=False)
    
    # Telegram-specific fields for operator onboarding
    telegram_link_token = Column(String(100), nullable=True, unique=True, index=True)  # Unique link for operator
    telegram_link_expires_at = Column(DateTime, nullable=True)
    telegram_link_used_at = Column(DateTime, nullable=True)
    
    # Relationships
    machine = relationship("Machine", back_populates="assignments")
    operator = relationship("User", back_populates="assigned_machines")
    
    __table_args__ = (
        # Conditional unique constraint for active assignments
        UniqueConstraint('machine_id', 'is_active', 
                        name='unique_active_assignment'),
        Index('idx_active_assignments', 'machine_id', 'is_active'),
        {"extend_existing": True}
    )

class LogIntent(enum.Enum):
    FUEL_LOG = "fuel_log"
    HOURS_LOG = "hours_log" 
    REPORT_ISSUE = "report_issue"

class FuelLog(Base):
    __tablename__ = "fuel_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=False, index=True)
    operator_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    fuel_volume = Column(Float, nullable=False)
    unit = Column(String(20), default="литров", nullable=False)
    
    # Message tracking
    telegram_message_id = Column(BigInteger, nullable=True)
    original_text = Column(Text, nullable=False)  # Original hashtag message
    parsed_data = Column(Text, nullable=True)  # JSON of parsed data for debugging
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    # Relationships
    machine = relationship("Machine", back_populates="fuel_logs")
    operator = relationship("User", back_populates="fuel_logs")
    
    __table_args__ = (
        CheckConstraint("fuel_volume > 0", name="positive_fuel_volume"),
        Index('idx_fuel_logs_date_machine', 'created_at', 'machine_id'),
        {"extend_existing": True}
    )

class HoursLog(Base):
    __tablename__ = "hours_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=False, index=True)
    operator_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    hours = Column(Float, nullable=False)
    unit = Column(String(20), default="часов", nullable=False)
    
    # Message tracking
    telegram_message_id = Column(BigInteger, nullable=True)
    original_text = Column(Text, nullable=False)
    parsed_data = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    # Relationships
    machine = relationship("Machine", back_populates="hours_logs")
    operator = relationship("User", back_populates="hours_logs")
    
    __table_args__ = (
        CheckConstraint("hours > 0", name="positive_hours"),
        Index('idx_hours_logs_date_machine', 'created_at', 'machine_id'),
        {"extend_existing": True}
    )

class IssueStatus(enum.Enum):
    REPORTED = "REPORTED"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"

class IssuePriority(enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

class IssueReport(Base):
    __tablename__ = "issue_reports"
    
    id = Column(Integer, primary_key=True, index=True)
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=False, index=True)
    operator_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    description = Column(Text, nullable=False)
    status = Column(String(20), default="REPORTED", nullable=False)
    priority = Column(String(20), default="MEDIUM", nullable=False)
    
    # Message tracking
    telegram_message_id = Column(BigInteger, nullable=True)
    original_text = Column(Text, nullable=False)
    parsed_data = Column(Text, nullable=True)
    
    # Issue management
    resolved_at = Column(DateTime, nullable=True)
    resolution_notes = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    machine = relationship("Machine", back_populates="issue_reports")
    operator = relationship("User", back_populates="issue_reports")
    
    __table_args__ = (
        CheckConstraint(
            "status IN ('REPORTED', 'IN_PROGRESS', 'RESOLVED', 'CLOSED')",
            name="valid_issue_status"
        ),
        CheckConstraint(
            "priority IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')",
            name="valid_issue_priority"
        ),
        Index('idx_issue_reports_status_date', 'status', 'created_at'),
        {"extend_existing": True}
    )

# Optional: Activity log for audit trail
class ActivityLog(Base):
    __tablename__ = "activity_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    action = Column(String(100), nullable=False)  # "MACHINE_ADDED", "OPERATOR_ASSIGNED", etc.
    entity_type = Column(String(50), nullable=False)  # "MACHINE", "USER", "ASSIGNMENT"
    entity_id = Column(Integer, nullable=False)
    details = Column(Text, nullable=True)  # JSON details of the action
    telegram_message_id = Column(BigInteger, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    # Relationship
    user = relationship("User")
    
    __table_args__ = (
        Index('idx_activity_logs_user_date', 'user_id', 'created_at'),
        {"extend_existing": True}
    )

# Optional: Settings table for bot configuration per owner
class OwnerSettings(Base):
    __tablename__ = "owner_settings"
    
    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    
    # Notification settings
    daily_report_enabled = Column(Boolean, default=True, nullable=False)
    daily_report_time = Column(String(5), default="18:00", nullable=False)  # HH:MM format
    issue_notification_enabled = Column(Boolean, default=True, nullable=False)
    fuel_alert_threshold = Column(Float, nullable=True)  # Alert when fuel below this
    
    # Telegram link settings
    link_expiry_hours = Column(Integer, default=24, nullable=False)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationship
    owner = relationship("User")
    
    __table_args__ = (
        CheckConstraint("link_expiry_hours > 0 AND link_expiry_hours <= 168", name="valid_expiry_hours"),  # Max 1 week
        {"extend_existing": True}
    )

class Group(Base):
    __tablename__ = "groups"
    
    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(BigInteger, nullable=False, unique=True, index=True)  # "-1001234567890"
    group_name = Column(String(255), nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    owner = relationship("User")
    messages: Mapped[List["GroupMessage"]] = relationship("GroupMessage", back_populates="group")
    
    __table_args__ = (
        Index('idx_groups_owner', 'owner_id'),
        {"extend_existing": True}
    )

class GroupMessage(Base):
    __tablename__ = "group_messages"
    
    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)  # NULL for unknown users
    
    # Telegram data
    telegram_user_id = Column(BigInteger, nullable=False, index=True)  # 123456789
    username = Column(String(100), nullable=True)
    first_name = Column(String(100), nullable=True)
    last_name = Column(String(100), nullable=True)
    telegram_message_id = Column(BigInteger, nullable=False, unique=True, index=True)  # 42
    
    # Message content
    message_text = Column(Text, nullable=False)
    message_type = Column(String(50), nullable=False)  # "regular|forwarded|forwarded_channel"
    
    # Message metadata
    reply_to_message_id = Column(BigInteger, nullable=True)  # For reply tracking
    original_sender = Column(String(255), nullable=True)  # For forwarded messages
    
    # Parsing/Processing
    parsed_data = Column(Text, nullable=True)  # JSON of NER extraction results
    processing_status = Column(String(50), default="pending", nullable=False)  # pending, processed, failed
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    group = relationship("Group", back_populates="messages")
    user = relationship("User")  # Optional, for recognized operators
    
    __table_args__ = (
        Index('idx_group_messages_date_group', 'created_at', 'group_id'),
        Index('idx_group_messages_user_date', 'telegram_user_id', 'created_at'),
        {"extend_existing": True}
    )