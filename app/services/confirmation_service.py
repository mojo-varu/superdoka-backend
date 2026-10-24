"""
app/services/confirmation_service.py

WP-E / ADR-0023: promotes a staged PendingConfirmation to a real
TimelineEvent (the ✅ path), or replaces its payload with a correction before
it was ever committed (the ✏️ path, when the pending item hasn't been
promoted yet). Engine-side module — no Telegram/aiogram imports.

Double-tap / stale-callback safety (SPEC-015-R06, R07) lives here: callers
(app/channels/telegram) get back a PromotionOutcome telling them exactly
what to answer the callback with, rather than re-deriving that logic.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PendingConfirmation, TimelineEvent
from app.schemas.fleet_update import FleetUpdate, Intent, MessageSource, Modality, SessionContext

# Reverse of EventProcessor._intent_to_event_type — only the intents that can
# ever reach a CONFIRM-route pending item (operational, loggable intents).
_EVENT_TYPE_TO_INTENT = {
    "FUEL_LOG": Intent.FUEL_LOG,
    "HOURS_LOG": Intent.HOURS_LOG,
    "ISSUE_REPORT": Intent.ISSUE_REPORT,
    "STATUS_UPDATE": Intent.STATUS_UPDATE,
    "PRODUCTION_LOG": Intent.PRODUCTION_LOG,
    "INSPECTION_CHECK": Intent.INSPECTION_CHECK,
    "PARTS_REQUEST": Intent.PARTS_REQUEST,
    "HANDOVER_NOTE": Intent.HANDOVER_NOTE,
}


class PromotionResult(str, Enum):
    COMMITTED = "committed"           # ✅ succeeded, exactly one new TimelineEvent
    ALREADY_RESOLVED = "already_resolved"   # double tap — SPEC-015-R06
    EXPIRED_OR_MISSING = "expired_or_missing"   # stale callback — SPEC-015-R07


@dataclass
class PromotionOutcome:
    result: PromotionResult
    timeline_event_id: Optional[int] = None


async def promote_pending_confirmation(
    db: AsyncSession,
    pending_id: int,
) -> PromotionOutcome:
    """
    The ✅ path. Idempotent: a second call with the same pending_id returns
    ALREADY_RESOLVED and performs no write (AC-015-04).
    """
    result = await db.execute(select(PendingConfirmation).where(PendingConfirmation.id == pending_id))
    pending = result.scalar_one_or_none()

    if pending is None:
        return PromotionOutcome(PromotionResult.EXPIRED_OR_MISSING)
    if pending.resolved_at is not None:
        return PromotionOutcome(PromotionResult.ALREADY_RESOLVED, pending.resolved_event_id)
    if pending.expires_at < datetime.utcnow():
        return PromotionOutcome(PromotionResult.EXPIRED_OR_MISSING)

    intent = _EVENT_TYPE_TO_INTENT.get(pending.event_type)
    if intent is None:
        return PromotionOutcome(PromotionResult.EXPIRED_OR_MISSING)

    # Reconstruct a minimal FleetUpdate for the shared _commit_event path.
    update = FleetUpdate.from_raw(
        source=MessageSource.TELEGRAM,
        operator_id=str(pending.operator_id),   # not the platform id, but _commit_event never reads this field — only operator_db_id below
        chat_id="",
        raw_text=pending.raw_text or "",
        modality=Modality.TEXT,
    )
    update.operator_db_id = pending.operator_id
    update.intent = intent
    update.entities = pending.payload or {}
    update.session = SessionContext(machine_id=pending.machine_id)
    update.confidence = 1.0   # operator-confirmed — treat as ground truth for the write path
    object.__setattr__(update, "via_llm", False)

    from app.services.event_processor import event_processor
    await event_processor._commit_event(db, update)

    pending.resolved_at = datetime.utcnow()
    pending.resolved_event_id = update.timeline_event_id
    await db.commit()

    return PromotionOutcome(PromotionResult.COMMITTED, update.timeline_event_id)


async def replace_pending_payload(
    db: AsyncSession,
    pending_id: int,
    new_payload: dict,
    new_raw_text: Optional[str] = None,
) -> bool:
    """
    The ✏️ path when the pending item has NOT been committed yet
    (SPEC-015-R08 first branch: "if the original item was not yet committed,
    it replaces the pending value"). Returns False for a stale/expired/
    already-resolved pending_id (caller should fall back to the stale-callback
    reply) rather than raising.
    """
    result = await db.execute(select(PendingConfirmation).where(PendingConfirmation.id == pending_id))
    pending = result.scalar_one_or_none()
    if pending is None or pending.resolved_at is not None or pending.expires_at < datetime.utcnow():
        return False

    pending.payload = new_payload
    if new_raw_text is not None:
        pending.raw_text = new_raw_text
    await db.commit()
    return True
