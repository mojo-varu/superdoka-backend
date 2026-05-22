from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func
from sqlalchemy.orm import selectinload
from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from datetime import datetime, timedelta, timezone
import logging
import secrets
import string
from enum import Enum

# Import your existing dependencies
from app.db.database import get_db
from app.db.models import (
    User, Machine, MachineAssignment, FuelLog, HoursLog, IssueReport,
    ActivityLog, ActiveSession, ConversationLog, MachineState, TimelineEvent,
)
from app.api.deps import get_any_platform_user, require_owner

logger = logging.getLogger(__name__)

operator_router = APIRouter(tags=["Operator Operations"])

class PhoneVerificationRequest(BaseModel):
    token: str
    phone: str

# Operator Operations
@operator_router.post("/verify-phone")
async def verify_operator_phone(
    request: PhoneVerificationRequest,
    current_user: User = Depends(get_any_platform_user()),
    db: AsyncSession = Depends(get_db)
):
    """Verify operator phone number and establish platform_user_id mapping"""
    try:
        # Find assignment by token
        assignment_result = await db.execute(
            select(MachineAssignment)
            .options(selectinload(MachineAssignment.operator), selectinload(MachineAssignment.machine))
            .where(
                and_(
                    MachineAssignment.telegram_link_token == request.token,
                    MachineAssignment.telegram_link_expires_at > datetime.utcnow(),
                    MachineAssignment.is_active == True
                )
            )
        )
        assignment = assignment_result.scalar_one_or_none()
        
        if not assignment:
            raise HTTPException(status_code=400, detail="Invalid or expired token")
        
        # Verify phone number matches operator
        if assignment.operator.mobile != request.phone:
            raise HTTPException(status_code=400, detail="Phone number does not match assigned operator")
        
        # Update operator with platform_user_id
        assignment.operator.platform_user_id = current_user.platform_user_id
        assignment.telegram_link_used_at = datetime.utcnow()
        
        await db.commit()
        
        # Log activity
        activity = ActivityLog(
            user_id=assignment.operator.id,
            action="OPERATOR_VERIFIED",
            entity_type="USER",
            entity_id=assignment.operator.id,
            details=f"Operator verified telegram access for machine {assignment.machine.reg_number}"
        )
        db.add(activity)
        await db.commit()
        
        return {
            "verified": True,
            "operator_name": assignment.operator.name,
            "machine_reg_number": assignment.machine.reg_number,
            "machine_model": assignment.machine.model
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error verifying operator phone: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# Sandbox read endpoints (no auth — used by demo screens)
# ---------------------------------------------------------------------------

def _initials(name: str) -> str:
    parts = name.split()
    return (parts[0][0] + parts[1][0]).upper() if len(parts) >= 2 else name[:2].upper()


@operator_router.get("/list")
async def list_operators(db: AsyncSession = Depends(get_db)):
    """
    List all operators with their assigned machines and shift status.
    Powers the left-panel operator list in the operator console.
    """
    operators = (await db.execute(
        select(User).where(User.user_type == "OPERATOR", User.is_active == True).order_by(User.name)
    )).scalars().all()

    if not operators:
        return []

    op_ids = [op.id for op in operators]

    # Last active timestamp per operator from ConversationLog
    last_active_rows = (await db.execute(
        select(ConversationLog.operator_id, func.max(ConversationLog.created_at).label("last_at"))
        .where(ConversationLog.operator_id.in_(op_ids))
        .group_by(ConversationLog.operator_id)
    )).all()
    last_active_map: dict[int, datetime] = {row.operator_id: row.last_at for row in last_active_rows}

    # Active sessions keyed by operator_id
    sessions = {
        s.operator_id: s
        for s in (await db.execute(
            select(ActiveSession).where(ActiveSession.operator_id.in_(op_ids))
        )).scalars().all()
    }

    # All assignments with machines
    rows = (await db.execute(
        select(MachineAssignment, Machine, MachineState)
        .join(Machine, Machine.id == MachineAssignment.machine_id)
        .outerjoin(MachineState, MachineState.machine_id == Machine.id)
        .where(MachineAssignment.operator_id.in_(op_ids))
        .order_by(MachineAssignment.is_active.desc())
    )).all()

    # Group assignments by operator
    assignments_by_op: Dict[int, list] = {op.id: [] for op in operators}
    for assignment, machine, state in rows:
        assignments_by_op[assignment.operator_id].append({
            "reg_number":        machine.reg_number,
            "machine_type":      machine.machine_type,
            "status":            (state.status if state else "IDLE").lower(),
            "is_session_machine": (
                sessions.get(assignment.operator_id) is not None
                and sessions[assignment.operator_id].machine_id == machine.id
            ),
        })

    # ---------------------------------------------------------------
    # Shift stats (bulk queries keyed by operator_id)
    # ---------------------------------------------------------------
    now         = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    days_30_ago = now - timedelta(days=30)

    # completed_shifts_today: count of SHIFT_END per operator today
    shifts_today_rows = (await db.execute(
        select(TimelineEvent.operator_id, func.count(TimelineEvent.id).label("cnt"))
        .where(
            TimelineEvent.event_type == "SHIFT_END",
            TimelineEvent.created_at >= today_start,
            TimelineEvent.operator_id.in_(op_ids),
        )
        .group_by(TimelineEvent.operator_id)
    )).all()
    shifts_today_map: Dict[int, int] = {row.operator_id: row.cnt for row in shifts_today_rows}

    # last_shift_ended_at: most recent SHIFT_END per operator
    last_end_rows = (await db.execute(
        select(TimelineEvent.operator_id, func.max(TimelineEvent.created_at).label("last_end"))
        .where(
            TimelineEvent.event_type == "SHIFT_END",
            TimelineEvent.operator_id.in_(op_ids),
        )
        .group_by(TimelineEvent.operator_id)
    )).all()
    last_end_map: Dict[int, datetime] = {row.operator_id: row.last_end for row in last_end_rows}

    # avg_shift_duration_30d_minutes: fetch all SHIFT_END + SHIFT_START in last 30d, pair them
    all_shift_events_30d = (await db.execute(
        select(TimelineEvent)
        .where(
            TimelineEvent.event_type.in_(["SHIFT_START", "SHIFT_END"]),
            TimelineEvent.created_at >= days_30_ago,
            TimelineEvent.operator_id.in_(op_ids),
        )
        .order_by(TimelineEvent.operator_id, TimelineEvent.machine_id, TimelineEvent.created_at)
    )).scalars().all()

    # Group by (operator_id, machine_id) for pairing
    from collections import defaultdict
    events_by_op_machine: Dict = defaultdict(list)
    for ev in all_shift_events_30d:
        events_by_op_machine[(ev.operator_id, ev.machine_id)].append(ev)

    # For each operator, collect durations of completed shifts
    op_durations: Dict[int, list] = defaultdict(list)
    for (op_id, _machine_id), evs in events_by_op_machine.items():
        # Walk events in order; pair each SHIFT_END with most recent preceding SHIFT_START
        last_start = None
        for ev in evs:
            if ev.event_type == "SHIFT_START":
                last_start = ev
            elif ev.event_type == "SHIFT_END" and last_start is not None:
                dur = int((ev.created_at - last_start.created_at).total_seconds() / 60)
                op_durations[op_id].append(dur)
                last_start = None  # consume the start

    avg_30d_map: Dict[int, Optional[int]] = {}
    for op_id in op_ids:
        durs = op_durations.get(op_id, [])
        avg_30d_map[op_id] = int(sum(durs) / len(durs)) if len(durs) >= 3 else None

    # ---------------------------------------------------------------
    result = []
    for op in operators:
        session = sessions.get(op.id)
        active_machine = None
        if session:
            for a in assignments_by_op[op.id]:
                if a["is_session_machine"]:
                    active_machine = a["reg_number"]
                    break

        last_at = last_active_map.get(op.id)
        last_end = last_end_map.get(op.id)
        result.append({
            "id":             op.id,
            "name":           op.name,
            "initials":       _initials(op.name),
            "platform_user_id": op.platform_user_id,
            "is_on_shift":    session is not None and session.shift_state == "ACTIVE",
            "active_machine": active_machine,
            "machines":       assignments_by_op[op.id],
            "last_active_at": last_at.isoformat() if last_at else None,
            "completed_shifts_today":         shifts_today_map.get(op.id, 0),
            "last_shift_ended_at":            last_end.isoformat() if last_end else None,
            "avg_shift_duration_30d_minutes": avg_30d_map.get(op.id),
        })

    return result


@operator_router.get("/{operator_id}/machines")
async def operator_machines(operator_id: int, db: AsyncSession = Depends(get_db)):
    """Machines assigned to this operator with live status."""
    op = (await db.execute(
        select(User).where(User.id == operator_id, User.user_type == "OPERATOR")
    )).scalar_one_or_none()
    if not op:
        raise HTTPException(status_code=404, detail="Operator not found")

    session = (await db.execute(
        select(ActiveSession).where(ActiveSession.operator_id == operator_id)
    )).scalar_one_or_none()

    rows = (await db.execute(
        select(MachineAssignment, Machine, MachineState)
        .join(Machine, Machine.id == MachineAssignment.machine_id)
        .outerjoin(MachineState, MachineState.machine_id == Machine.id)
        .where(MachineAssignment.operator_id == operator_id)
        .order_by(MachineAssignment.is_active.desc())
    )).all()

    return [
        {
            "reg_number":        m.reg_number,
            "machine_type":      m.machine_type,
            "model":             m.model,
            "year":              m.year,
            "status":            (state.status if state else "IDLE").lower(),
            "is_active_assignment": a.is_active,
            "is_session_machine": (
                session is not None and session.machine_id == m.id
                and session.shift_state == "ACTIVE"
            ),
            "fuel_today":        state.fuel_added_today   if state else 0,
            "hours_today":       state.hours_worked_today if state else 0,
        }
        for a, m, state in rows
    ]


@operator_router.get("/{operator_id}/timeline")
async def operator_timeline(operator_id: int, limit: int = 50, db: AsyncSession = Depends(get_db)):
    """
    Recent timeline events for this operator (across all their machines).
    Powers the chat history panel in the operator console.
    """
    op = (await db.execute(
        select(User).where(User.id == operator_id, User.user_type == "OPERATOR")
    )).scalar_one_or_none()
    if not op:
        raise HTTPException(status_code=404, detail="Operator not found")

    events = (await db.execute(
        select(TimelineEvent, Machine)
        .join(Machine, Machine.id == TimelineEvent.machine_id)
        .where(TimelineEvent.operator_id == operator_id)
        .order_by(TimelineEvent.created_at)
        .limit(limit)
    )).all()

    return [
        {
            "id":          e.id,
            "event_type":  e.event_type.lower(),
            "raw_text":    e.raw_text,
            "machine_reg": m.reg_number,
            "content":     e.content,
            "confidence":  round(e.confidence, 2) if e.confidence else None,
            "via_llm":     e.via_llm,
            "time":        e.created_at.strftime("%H:%M"),
            "created_at":  e.created_at.isoformat(),
        }
        for e, m in events
    ]


@operator_router.get("/{operator_id}/conversation")
async def operator_conversation(
    operator_id: int,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """
    Full conversation history for an operator from ConversationLog, newest first.
    Returns in chronological order (oldest → newest) for the chat UI.
    Covers all intents including non-operational turns.
    """
    op = (await db.execute(
        select(User).where(User.id == operator_id, User.user_type == "OPERATOR")
    )).scalar_one_or_none()
    if not op:
        raise HTTPException(status_code=404, detail="Operator not found")

    rows = (await db.execute(
        select(ConversationLog)
        .where(ConversationLog.operator_id == operator_id)
        .order_by(ConversationLog.created_at.desc())
        .limit(limit)
    )).scalars().all()

    return [
        {
            "id":         log.id,
            "raw_text":   log.raw_text,
            "intent":     log.intent,
            "confidence": round(log.confidence, 3) if log.confidence is not None else None,
            "vfm_reply":  log.vfm_reply,
            "source":     log.source,
            "created_at": log.created_at.isoformat(),
        }
        for log in reversed(rows)
    ]


@operator_router.get("/{operator_id}/shifts")
async def operator_shifts(
    operator_id: int,
    limit: int = 30,
    db: AsyncSession = Depends(get_db),
):
    """
    Completed and active shifts for an operator, each with its events summarised.
    Sorted newest first. Used by the Operators tab shift history pane.
    """
    op = (await db.execute(
        select(User).where(User.id == operator_id, User.user_type == "OPERATOR")
    )).scalar_one_or_none()
    if not op:
        raise HTTPException(status_code=404, detail="Operator not found")

    all_events = (await db.execute(
        select(TimelineEvent)
        .where(TimelineEvent.operator_id == operator_id)
        .order_by(TimelineEvent.created_at.asc())
    )).scalars().all()

    # ── Walk events to build shift buckets ──────────────────────────────────
    buckets: list = []          # completed + final open bucket
    current_bucket: Optional[dict] = None

    for ev in all_events:
        if ev.event_type == "SHIFT_START":
            # Close any currently open bucket as "open" (no SHIFT_END seen)
            if current_bucket is not None:
                current_bucket["status"] = "open"
                buckets.append(current_bucket)
            # Open a new bucket
            current_bucket = {
                "machine_id": ev.machine_id,
                "started_at": ev.created_at,
                "ended_at":   None,
                "status":     "open",
                "events":     [ev],
            }
        elif ev.event_type == "SHIFT_END":
            if current_bucket is not None:
                current_bucket["events"].append(ev)
                current_bucket["ended_at"] = ev.created_at
                current_bucket["status"]   = "completed"
                buckets.append(current_bucket)
                current_bucket = None
            # else: orphaned SHIFT_END with no preceding start — ignore
        else:
            # Any other event appended to the current open bucket
            if current_bucket is not None:
                current_bucket["events"].append(ev)

    # If a bucket is still open after walking all events
    if current_bucket is not None:
        current_bucket["status"] = "open"
        buckets.append(current_bucket)

    # ── Bulk-fetch Machine rows ──────────────────────────────────────────────
    machine_ids = list({b["machine_id"] for b in buckets if b["machine_id"] is not None})
    machines_map: Dict[int, "Machine"] = {}
    if machine_ids:
        machine_rows = (await db.execute(
            select(Machine).where(Machine.id.in_(machine_ids))
        )).scalars().all()
        machines_map = {m.id: m for m in machine_rows}

    # ── Assign 1-based shift_number (oldest = 1) and sort newest first ───────
    for i, b in enumerate(buckets):
        b["shift_number"] = i + 1

    now = datetime.utcnow()
    result_list = []
    for b in reversed(buckets):          # newest first
        m_id      = b["machine_id"]
        machine   = machines_map.get(m_id)
        started   = b["started_at"]
        ended     = b.get("ended_at")

        duration_minutes = int(
            ((ended if ended else now) - started).total_seconds() / 60
        )

        evs = b["events"]
        fuel_total  = sum(
            float(ev.content.get("fuel_volume", 0) or 0)
            for ev in evs if ev.event_type == "FUEL_LOG"
        )
        hours_total = sum(
            float(ev.content.get("hours", 0) or 0)
            for ev in evs if ev.event_type == "HOURS_LOG"
        )
        issue_count = sum(1 for ev in evs if ev.event_type == "ISSUE_REPORT")

        result_list.append({
            "shift_number":     b["shift_number"],
            "machine_id":       m_id,
            "machine_alias":    (machine.alias or machine.reg_number) if machine else str(m_id),
            "reg_number":       machine.reg_number if machine else "",
            "started_at":       started.isoformat(),
            "ended_at":         ended.isoformat() if ended else None,
            "duration_minutes": duration_minutes,
            "status":           b["status"],
            "events": [
                {
                    "event_type": ev.event_type,
                    "created_at": ev.created_at.isoformat(),
                    "raw_text":   ev.raw_text or "",
                    "content":    ev.content or {},
                }
                for ev in evs
            ],
            "summary": {
                "fuel_total":  round(fuel_total, 2),
                "hours_total": round(hours_total, 2),
                "issue_count": issue_count,
                "event_count": len(evs),
            },
        })

    return result_list[:limit]
