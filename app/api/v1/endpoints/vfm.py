"""
app/api/v1/endpoints/vfm.py  — Hour 8b

The unified VFM endpoint. Thin HTTP wrapper around EventProcessor.
All business logic lives in services/, not here.

Endpoints:
  POST /api/v1/vfm/update          — main message ingest (real-time path)
  POST /api/v1/vfm/correct/{event_id} — operator correction flow
  GET  /api/v1/vfm/status          — current fleet state (owner dashboard feed)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_async_session
from app.db.models import MachineState, TimelineEvent, User
from app.schemas.fleet_update import FleetUpdate, MessageSource, Modality
from app.services.event_processor import event_processor

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/vfm", tags=["VFM"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class VFMUpdateRequest(BaseModel):
    """Inbound message from any adapter (Telegram bot, MAX bridge, REST client)."""
    operator_id: str
    chat_id:        str
    text:           str
    source:         str = "telegram"   # "telegram" | "max" | "rest"
    modality:       str = "text"       # "text" | "voice" | "image"
    media_url:      Optional[str] = None
    message_id:     Optional[str] = None


class VFMUpdateResponse(BaseModel):
    reply:              str
    intent:             str
    confidence:         float
    confidence_route:   str
    timeline_event_id:  Optional[int]
    needs_confirmation: bool
    rules_fired:        list
    errors:             list


class CorrectionRequest(BaseModel):
    field:    str    # e.g. "fuel_volume"
    new_value: Any


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/update", response_model=VFMUpdateResponse)
async def process_update(
    request: VFMUpdateRequest,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Main entry point for all inbound operator messages.
    Called by the Telegram/MAX adapter on every message.
    """
    update = FleetUpdate.from_raw(
        source         = MessageSource(request.source),
        operator_id = request.operator_id,
        chat_id        = request.chat_id,
        raw_text       = request.text,
        modality       = Modality(request.modality),
        media_url      = request.media_url,
        message_id     = request.message_id,
    )

    processed = await event_processor.process(db, update)

    return VFMUpdateResponse(
        reply              = processed.reply_text or "",
        intent             = processed.intent,
        confidence         = round(processed.confidence, 3),
        confidence_route   = processed.confidence_route,
        timeline_event_id  = processed.timeline_event_id,
        needs_confirmation = processed.needs_confirmation,
        rules_fired        = processed.rules_fired,
        errors             = processed.processing_errors,
    )


@router.post("/correct/{event_id}", status_code=200)
async def correct_event(
    event_id:   int,
    correction: CorrectionRequest,
    db:         AsyncSession = Depends(get_async_session),
):
    """
    Operator taps "Исправить ✗" — submit a correction to a previous event.
    Creates a new CORRECTION TimelineEvent pointing to the original.
    Original event is preserved (immutable ledger).
    """
    result = await db.execute(
        select(TimelineEvent).where(TimelineEvent.id == event_id)
    )
    original = result.scalar_one_or_none()
    if not original:
        raise HTTPException(status_code=404, detail="Event not found")

    old_value = original.content.get(correction.field)
    correction_event = TimelineEvent(
        machine_id         = original.machine_id,
        operator_id        = original.operator_id,
        event_type         = "CORRECTION",
        content            = {
            "original_event_id": event_id,
            "field":     correction.field,
            "old_value": old_value,
            "new_value": correction.new_value,
        },
        raw_text           = f"Correction: {correction.field} {old_value} → {correction.new_value}",
        corrected_event_id = event_id,
    )
    db.add(correction_event)
    await db.commit()

    return {"status": "corrected", "correction_event_id": correction_event.id}


@router.get("/status")
async def fleet_status(
    db: AsyncSession = Depends(get_async_session),
) -> Dict[str, Any]:
    """
    Live fleet state — feeds the owner dashboard.
    Returns MachineState for all active machines.
    """
    result = await db.execute(
        select(MachineState).where(
            MachineState.status.in_(["WORKING", "WARNING", "DOWN"])
        )
    )
    states = result.scalars().all()

    return {
        "active_machines": len(states),
        "machines": [
            {
                "machine_id":        s.machine_id,
                "status":            s.status,
                "active_operator_id":s.active_operator_id,
                "fuel_added_today":  s.fuel_added_today,
                "hours_worked_today":s.hours_worked_today,
                "open_issue_count":  s.open_issue_count,
                "last_event_at":     s.last_event_at.isoformat() if s.last_event_at else None,
            }
            for s in states
        ],
    }
