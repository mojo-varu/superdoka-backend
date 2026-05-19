from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import selectinload
from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from datetime import datetime, timedelta
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

    result = []
    for op in operators:
        session = sessions.get(op.id)
        active_machine = None
        if session:
            for a in assignments_by_op[op.id]:
                if a["is_session_machine"]:
                    active_machine = a["reg_number"]
                    break

        result.append({
            "id":             op.id,
            "name":           op.name,
            "initials":       _initials(op.name),
            "platform_user_id": op.platform_user_id,
            "is_on_shift":    session is not None and session.shift_state == "ACTIVE",
            "active_machine": active_machine,
            "machines":       assignments_by_op[op.id],
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
