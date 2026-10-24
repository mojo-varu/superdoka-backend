"""
app/services/correction_service.py

Shared correction logic — extracted from
app/api/v1/endpoints/vfm.py::correct_event so that app/channels/telegram's
✏️ flow can call the same logic in-process (SPEC-015-R08: "by calling the
same logic POST /correct/{event_id} calls, in-process, not over HTTP").

Engine-side module (app/services) — no Telegram/aiogram imports here.
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TimelineEvent


class EventNotFound(Exception):
    pass


async def apply_correction(
    db: AsyncSession,
    event_id: int,
    field: str,
    new_value: Any,
) -> TimelineEvent:
    """
    Create a new CORRECTION TimelineEvent pointing at event_id. The original
    event is never modified (ADR-0005, SPEC-004-R06). Raises EventNotFound if
    event_id does not exist. Does not commit the caller's transaction if one
    is already open at a higher level — callers that need atomicity with
    other writes should wrap this and commit once; the direct HTTP endpoint
    commits immediately for backward compatibility.
    """
    result = await db.execute(select(TimelineEvent).where(TimelineEvent.id == event_id))
    original = result.scalar_one_or_none()
    if not original:
        raise EventNotFound(f"TimelineEvent {event_id} not found")

    old_value = (original.content or {}).get(field)
    correction_event = TimelineEvent(
        machine_id=original.machine_id,
        operator_id=original.operator_id,
        event_type="CORRECTION",
        content={
            "original_event_id": event_id,
            "field": field,
            "old_value": old_value,
            "new_value": new_value,
        },
        raw_text=f"Correction: {field} {old_value} → {new_value}",
        corrected_event_id=event_id,
    )
    db.add(correction_event)
    return correction_event


async def resolve_correction_target(
    db: AsyncSession,
    operator_id: int,
    machine_id: int,
    preferred_event_id: Optional[int] = None,
) -> Optional[TimelineEvent]:
    """
    SPEC-001-R11: when a correction has no explicit target (free-text
    "не 150, а 105" rather than a ✏️ tap on a specific message), resolve to
    the most recent matching event in the operator's current session.
    If preferred_event_id is given (the ✏️ button case — SPEC-015-R08), it
    always wins. Returns None if nothing matches (caller should CLARIFY).
    """
    if preferred_event_id is not None:
        result = await db.execute(select(TimelineEvent).where(TimelineEvent.id == preferred_event_id))
        return result.scalar_one_or_none()

    result = await db.execute(
        select(TimelineEvent)
        .where(
            TimelineEvent.operator_id == operator_id,
            TimelineEvent.machine_id == machine_id,
            TimelineEvent.event_type != "CORRECTION",
        )
        .order_by(TimelineEvent.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()
