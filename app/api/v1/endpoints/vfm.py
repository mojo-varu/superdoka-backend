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
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_async_session
from app.db.models import ActiveSession, FuelLog, HoursLog, IssueReport, Machine, MachineAssignment, MachineState, TimelineEvent, User
from app.schemas.fleet_update import FleetUpdate, MessageSource, Modality
from app.core.model_loader import models_ready
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
        "pipeline": models_ready(),
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


@router.get("/fleet/intelligence")
async def fleet_intelligence(
    db: AsyncSession = Depends(get_async_session),
) -> Dict[str, Any]:
    """
    Fleet intelligence summary for the owner dashboard.
    Joins Machine + MachineState, computes fuel_rate, baseline, and anomaly flag.
    """
    now         = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago    = today_start - timedelta(days=7)

    rows_result = await db.execute(
        select(Machine, MachineState)
        .outerjoin(MachineState, MachineState.machine_id == Machine.id)
        .where(Machine.is_active == True)
        .order_by(Machine.id)
    )
    rows = rows_result.all()

    machines_out = []
    for machine, state in rows:
        _ft = (await db.execute(
            select(func.sum(FuelLog.fuel_volume)).where(
                FuelLog.machine_id == machine.id,
                FuelLog.created_at >= today_start,
            )
        )).scalar()
        _ht = (await db.execute(
            select(func.sum(HoursLog.hours)).where(
                HoursLog.machine_id == machine.id,
                HoursLog.created_at >= today_start,
            )
        )).scalar()
        fuel_today  = float(_ft or 0)
        hours_today = float(_ht or 0)
        open_issues = int(state.open_issue_count or 0) if state else 0
        status      = state.status                         if state else "IDLE"
        last_event  = state.last_event_at                  if state else None
        active_op   = state.active_operator_id             if state else None

        fuel_rate = round(fuel_today / hours_today, 1) if hours_today > 0 else None

        # Baseline: average L/h from the previous 7 days (excluding today)
        fuel_baseline = None
        bl_fuel = (await db.execute(
            select(func.sum(FuelLog.fuel_volume)).where(
                FuelLog.machine_id == machine.id,
                FuelLog.created_at >= week_ago,
                FuelLog.created_at <  today_start,
            )
        )).scalar()
        bl_hrs = (await db.execute(
            select(func.sum(HoursLog.hours)).where(
                HoursLog.machine_id == machine.id,
                HoursLog.created_at >= week_ago,
                HoursLog.created_at <  today_start,
            )
        )).scalar()
        if bl_hrs and float(bl_hrs) > 0:
            fuel_baseline = round(float(bl_fuel or 0) / float(bl_hrs), 1)

        anomaly = bool(
            fuel_rate is not None
            and fuel_baseline is not None
            and fuel_rate > fuel_baseline * 1.20
        )

        last_contact = (
            int((now - last_event).total_seconds() / 60)
            if last_event else None
        )

        machines_out.append({
            "reg_number":               machine.reg_number,
            "alias":                    machine.alias or machine.reg_number,
            "type":                     machine.machine_type,
            "status":                   status,
            "fuel_today":               fuel_today,
            "hours_today":              hours_today,
            "fuel_rate":                fuel_rate,
            "fuel_baseline":            fuel_baseline,
            "anomaly":                  anomaly,
            "open_issues":              open_issues,
            "last_contact_minutes_ago": last_contact,
            "shift_active":             active_op is not None,
        })

    return {
        "machines": machines_out,
        "summary": {
            "total_machines":    len(machines_out),
            "active_shifts":     sum(1 for m in machines_out if m["shift_active"]),
            "total_anomalies":   sum(1 for m in machines_out if m["anomaly"]),
            "total_open_issues": sum(m["open_issues"] for m in machines_out),
        },
    }


@router.get("/machine/{reg_number}/state")
async def machine_state_detail(
    reg_number: str,
    db: AsyncSession = Depends(get_async_session),
) -> Dict[str, Any]:
    """
    Per-machine detail view: state snapshot + list of open issues.
    reg_number must match the stored value exactly (as returned by /fleet/intelligence).
    """
    machine_result = await db.execute(
        select(Machine).where(Machine.reg_number == reg_number)
    )
    machine = machine_result.scalar_one_or_none()
    if not machine:
        raise HTTPException(status_code=404, detail=f"Machine '{reg_number}' not found")

    state_result = await db.execute(
        select(MachineState).where(MachineState.machine_id == machine.id)
    )
    state = state_result.scalar_one_or_none()

    now         = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    fuel_today = float((await db.execute(
        select(func.sum(FuelLog.fuel_volume)).where(
            FuelLog.machine_id == machine.id,
            FuelLog.created_at >= today_start,
        )
    )).scalar() or 0)

    hours_today = float((await db.execute(
        select(func.sum(HoursLog.hours)).where(
            HoursLog.machine_id == machine.id,
            HoursLog.created_at >= today_start,
        )
    )).scalar() or 0)

    issues_result = await db.execute(
        select(IssueReport, TimelineEvent)
        .outerjoin(TimelineEvent, TimelineEvent.id == IssueReport.timeline_event_id)
        .where(
            IssueReport.machine_id == machine.id,
            IssueReport.status.in_(["REPORTED", "IN_PROGRESS"]),
        )
        .order_by(IssueReport.created_at.desc())
    )

    open_issues = []
    for issue, event in issues_result.all():
        content   = (event.content or {}) if event else {}
        open_issues.append({
            "description": issue.description,
            "component":   content.get("component"),
            "severity":    content.get("severity"),
            "priority":    issue.priority,
            "created_at":  issue.created_at.isoformat(),
        })

    return {
        "machine": {
            "reg_number": machine.reg_number,
            "alias":      machine.alias or machine.reg_number,
            "type":       machine.machine_type,
        },
        "state": {
            "status":             state.status         if state else "IDLE",
            "fuel_added_today":   fuel_today,
            "hours_worked_today": hours_today,
            "open_issue_count":   state.open_issue_count if state else 0,
            "last_event_at":      state.last_event_at.isoformat() if state and state.last_event_at else None,
        },
        "open_issues": open_issues,
    }


@router.get("/sandbox/operators")
async def sandbox_operators(
    db: AsyncSession = Depends(get_async_session),
) -> Dict[str, Any]:
    """
    Sandbox init endpoint — returns all active operators with their primary machine.
    Prefers the machine from an active shift session; falls back to the first assignment.
    Used by the sandbox UI to populate the operator selector without hardcoding anything.
    """
    users_result = await db.execute(
        select(User).where(User.user_type == "OPERATOR", User.is_active == True).order_by(User.id)
    )
    users = users_result.scalars().all()

    # Active sessions keyed by operator DB id
    sessions_result = await db.execute(select(ActiveSession))
    active_map: dict[int, int] = {
        s.operator_id: s.machine_id for s in sessions_result.scalars().all()
    }

    # All active assignments keyed by operator DB id → list of machines
    assignments_result = await db.execute(
        select(MachineAssignment, Machine)
        .join(Machine, Machine.id == MachineAssignment.machine_id)
        .where(MachineAssignment.is_active == True)
        .order_by(MachineAssignment.machine_id)
    )
    assign_map: dict[int, list] = {}
    for asgn, mach in assignments_result.all():
        assign_map.setdefault(asgn.operator_id, []).append(mach)

    operators = []
    for user in users:
        # Pick the machine from the active session first, otherwise the first assignment
        machine = None
        active_machine_id = active_map.get(user.id)
        if active_machine_id:
            machine = next(
                (m for m in assign_map.get(user.id, []) if m.id == active_machine_id),
                None,
            )
        if machine is None and assign_map.get(user.id):
            machine = assign_map[user.id][0]

        operators.append({
            "platform_user_id":   user.platform_user_id,
            "name":               user.name,
            "machine_reg_number": machine.reg_number   if machine else None,
            "machine_alias":      machine.alias        if machine else None,
            "machine_type":       machine.machine_type if machine else None,
        })

    return {"operators": operators}
