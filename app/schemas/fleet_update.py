"""
app/schemas/fleet_update.py

The single domain object that crosses all three pillar boundaries.

  Interface pillar  → populates the top block (source, operator_id, raw_text …)
  Intelligence pillar → populates the middle block (intent, entities, confidence …)
  Agency pillar     → populates the bottom block (machine, session, actions …)

Rule: no pillar reaches into another's block directly.
Everything flows through this object.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Supporting enums / value objects
# ---------------------------------------------------------------------------

class MessageSource(str, Enum):
    TELEGRAM = "telegram"
    MAX      = "max"
    REST     = "rest"
    SANDBOX  = "sandbox"


class Modality(str, Enum):
    TEXT  = "text"
    VOICE = "voice"
    IMAGE = "image"
    FILE  = "file"


class ConfidenceRoute(str, Enum):
    """Decision made by the confidence router."""
    AUTO    = "auto"     # ≥ 0.85 — write immediately
    CONFIRM = "confirm"  # 0.60–0.85 — write + ask operator to confirm
    LLM     = "llm"      # < 0.60 — send to LLM fallback before writing


class Intent(str, Enum):
    SHIFT_START      = "shift_start"
    SHIFT_END        = "shift_end"
    FUEL_LOG         = "fuel_log"
    HOURS_LOG        = "hours_log"
    ISSUE_REPORT     = "issue_report"
    STATUS_UPDATE    = "status_update"
    PRODUCTION_LOG   = "production_log"
    INSPECTION_CHECK = "inspection_check"
    PARTS_REQUEST    = "parts_request"
    HANDOVER_NOTE    = "handover_note"
    MACHINE_SWITCH   = "machine_switch"
    # Owner admin (hashtag-anchored, always high confidence)
    ADD_MACHINE      = "add_machine"
    ASSIGN_MACHINE   = "assign_machine"
    # Fallback
    CLARIFICATION    = "clarification_needed"
    UNKNOWN          = "unknown"


class Severity(str, Enum):
    INFO     = "info"
    WARNING  = "warning"
    HIGH     = "high"
    CRITICAL = "critical"


# ---------------------------------------------------------------------------
# Action — emitted by the ActionPlanner, consumed by the messenger adapter
# ---------------------------------------------------------------------------

class Action(BaseModel):
    """
    A planned response to the operator or owner.
    The ActionPlanner produces a list of these; the adapter executes them.
    """
    action_type: str   # "reply_operator" | "alert_owner" | "alert_mechanic"
                       # | "create_procurement_ticket" | "nudge"
    recipient_id: Optional[str]  = None   # telegram/MAX user id
    message:      Optional[str]  = None   # text to send
    payload:      Dict[str, Any] = Field(default_factory=dict)
    priority:     str            = "normal"   # "low" | "normal" | "high" | "critical"


# ---------------------------------------------------------------------------
# Session context — populated by Agency / SessionService
# ---------------------------------------------------------------------------

class SessionContext(BaseModel):
    machine_id:          Optional[int]      = None
    machine_reg_number:  Optional[str]      = None
    machine_alias:       Optional[str]      = None
    machine_type:        Optional[str]      = None
    shift_started_at:    Optional[datetime] = None
    fuel_logged_today:   float              = 0.0
    hours_logged_today:  float              = 0.0
    open_issue_count:    int                = 0
    minutes_on_shift:    Optional[int]      = None   # computed at enrichment time


# ---------------------------------------------------------------------------
# The canonical FleetUpdate
# ---------------------------------------------------------------------------

class FleetUpdate(BaseModel):
    """
    Canonical domain object.  Created at the Ingest Boundary and passed
    through the full pipeline.  Each pillar fills in its section.

    ┌─────────────────────────────────────────┐
    │  Interface (ingest boundary fills this) │
    ├─────────────────────────────────────────┤
    │  Intelligence (NER / LLM fills this)    │
    ├─────────────────────────────────────────┤
    │  Agency (context engine fills this)     │
    └─────────────────────────────────────────┘
    """

    # ── Interface block ───────────────────────────────────────────────────
    update_id:    str         = Field(default_factory=lambda: str(uuid4()))
    source:       MessageSource = MessageSource.TELEGRAM
    modality:     Modality    = Modality.TEXT

    # Messenger-specific identifiers (strings so both Telegram int IDs
    # and MAX string IDs work without type divergence)
    operator_id: str           # the raw messenger user id (platform-agnostic)
    chat_id:        str       # group or DM chat id
    message_id:     Optional[str] = None

    raw_text:    str
    media_url:   Optional[str]      = None   # voice/photo download URL
    received_at: datetime           = Field(default_factory=datetime.utcnow)

    # DB foreign key — resolved by the ingest boundary from operator_id
    operator_db_id: Optional[int]  = None

    # ── Intelligence block ────────────────────────────────────────────────
    intent:     Intent              = Intent.UNKNOWN
    entities:   Dict[str, Any]      = Field(default_factory=dict)
    # Raw NER entities list (pre-merge, useful for debugging)
    raw_entities: List[Dict[str, Any]] = Field(default_factory=list)

    confidence:       float              = 0.0
    confidence_route: ConfidenceRoute    = ConfidenceRoute.LLM
    via_llm:          bool               = False   # True if LLM fallback was used

    # Derived from entities by Intelligence layer
    reg_number:   Optional[str]   = None   # machine reg from NER
    severity:     Optional[Severity] = None

    # ── Agency block ──────────────────────────────────────────────────────
    # Resolved by SessionService
    session: Optional[SessionContext] = None

    # Resolved by OntologyValidator
    ontology_valid:      bool           = True
    ontology_warnings:   List[str]      = Field(default_factory=list)

    # Set after TimelineEvent is written
    timeline_event_id: Optional[int]   = None

    # Fired rules
    rules_fired: List[str]             = Field(default_factory=list)

    # Actions planned by ActionPlanner (executed by adapter)
    actions: List[Action]              = Field(default_factory=list)

    # Final reply text (assembled by ActionPlanner for the adapter)
    reply_text:  Optional[str]         = None
    needs_confirmation: bool           = False   # True → inline keyboard shown

    # ── Pipeline audit ────────────────────────────────────────────────────
    processing_errors: List[str]       = Field(default_factory=list)
    processed_at:      Optional[datetime] = None

    class Config:
        use_enum_values = True

    # ── Convenience properties ────────────────────────────────────────────

    @property
    def machine_id(self) -> Optional[int]:
        return self.session.machine_id if self.session else None

    @property
    def has_active_session(self) -> bool:
        return self.session is not None and self.session.machine_id is not None

    @property
    def is_owner_admin_intent(self) -> bool:
        """Owner intents are hashtag-anchored and always treated as high-confidence."""
        return self.intent in (Intent.ADD_MACHINE, Intent.ASSIGN_MACHINE)

    @classmethod
    def from_raw(
        cls,
        *,
        source:         MessageSource,
        operator_id: str,
        chat_id:        str,
        raw_text:       str,
        modality:       Modality = Modality.TEXT,
        media_url:      Optional[str] = None,
        message_id:     Optional[str] = None,
    ) -> "FleetUpdate":
        """
        Factory used by all adapter ingest boundaries.
        Creates a FleetUpdate with the Interface block populated.
        Intelligence and Agency blocks filled in by downstream services.
        """
        return cls(
            source=source,
            operator_id=operator_id,
            chat_id=chat_id,
            raw_text=raw_text,
            modality=modality,
            media_url=media_url,
            message_id=message_id,
        )

    def set_confidence_route(self) -> None:
        """Compute and set confidence_route from the current confidence value."""
        if self.is_owner_admin_intent:
            self.confidence_route = ConfidenceRoute.AUTO
        elif self.confidence >= 0.85:
            self.confidence_route = ConfidenceRoute.AUTO
        elif self.confidence >= 0.60:
            self.confidence_route = ConfidenceRoute.CONFIRM
        else:
            self.confidence_route = ConfidenceRoute.LLM

    def add_error(self, error: str) -> None:
        self.processing_errors.append(error)

    def mark_processed(self) -> None:
        self.processed_at = datetime.utcnow()
