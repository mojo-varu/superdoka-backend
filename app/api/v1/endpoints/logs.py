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
    ActivityLog, TimelineEvent,
)
from app.api.deps import get_any_platform_user, require_owner

logger = logging.getLogger(__name__)

logs_router = APIRouter(tags=["Logging Operations"])

class LogResponse(BaseModel):
    id: int
    machine_reg_number: str
    operator_name: str
    created_at: datetime
    original_text: str

class FuelLogResponse(LogResponse):
    fuel_volume: float
    unit: str

class HoursLogResponse(LogResponse):
    hours: float
    unit: str

class IssueReportResponse(LogResponse):
    description: str
    status: str
    priority: str


# Logging Operations
@logs_router.post("/fuel")
async def log_fuel(
    log_data: dict,  # From your NER extraction
    current_user: User = Depends(get_any_platform_user()),
    db: AsyncSession = Depends(get_db)
):
    """Log fuel consumption"""
    try:
        # Validate current user is an operator
        if current_user.user_type != UserTypeEnum.OPERATOR.value:
            raise HTTPException(status_code=403, detail="Only operators can log data")
        
        # Get machine and verify operator assignment
        reg_number = log_data.get("reg_number")
        machine_result = await db.execute(
            select(Machine)
            .join(MachineAssignment)
            .where(
                and_(
                    Machine.reg_number == reg_number,
                    MachineAssignment.operator_id == current_user.id,
                    MachineAssignment.is_active == True
                )
            )
        )
        machine = machine_result.scalar_one_or_none()
        
        if not machine:
            raise HTTPException(status_code=404, detail="Machine not found or not assigned to you")
        
        # Create fuel log
        fuel_log = FuelLog(
            machine_id=machine.id,
            operator_id=current_user.id,
            fuel_volume=log_data.get("fuel_volume"),
            unit=log_data.get("unit", "литров"),
            original_text=log_data.get("text"),
            parsed_data=str(log_data)
        )
        
        db.add(fuel_log)
        await db.commit()
        await db.refresh(fuel_log)
        
        return {"message": "Fuel log recorded successfully", "log_id": fuel_log.id}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error logging fuel: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@logs_router.post("/hours")
async def log_hours(
    log_data: dict,  # From your NER extraction
    current_user: User = Depends(get_any_platform_user()),
    db: AsyncSession = Depends(get_db)
):
    """Log machine hours"""
    try:
        # Validate current user is an operator
        if current_user.user_type != UserTypeEnum.OPERATOR.value:
            raise HTTPException(status_code=403, detail="Only operators can log data")
        
        # Get machine and verify operator assignment
        reg_number = log_data.get("reg_number")
        machine_result = await db.execute(
            select(Machine)
            .join(MachineAssignment)
            .where(
                and_(
                    Machine.reg_number == reg_number,
                    MachineAssignment.operator_id == current_user.id,
                    MachineAssignment.is_active == True
                )
            )
        )
        machine = machine_result.scalar_one_or_none()
        
        if not machine:
            raise HTTPException(status_code=404, detail="Machine not found or not assigned to you")
        
        # Create hours log
        hours_log = HoursLog(
            machine_id=machine.id,
            operator_id=current_user.id,
            hours=log_data.get("hours"),
            unit=log_data.get("unit", "часов"),
            original_text=log_data.get("text"),
            parsed_data=str(log_data)
        )
        
        db.add(hours_log)
        await db.commit()
        await db.refresh(hours_log)
        
        return {"message": "Hours log recorded successfully", "log_id": hours_log.id}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error logging hours: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@logs_router.post("/issue")
async def report_issue(
    log_data: dict,  # From your NER extraction
    current_user: User = Depends(get_any_platform_user()),
    db: AsyncSession = Depends(get_db)
):
    """Report machine issue"""
    try:
        # Validate current user is an operator
        if current_user.user_type != UserTypeEnum.OPERATOR.value:
            raise HTTPException(status_code=403, detail="Only operators can log data")
        
        # Get machine and verify operator assignment
        reg_number = log_data.get("reg_number")
        machine_result = await db.execute(
            select(Machine)
            .join(MachineAssignment)
            .where(
                and_(
                    Machine.reg_number == reg_number,
                    MachineAssignment.operator_id == current_user.id,
                    MachineAssignment.is_active == True
                )
            )
        )
        machine = machine_result.scalar_one_or_none()
        
        if not machine:
            raise HTTPException(status_code=404, detail="Machine not found or not assigned to you")
        
        # Create issue report
        issue_report = IssueReport(
            machine_id=machine.id,
            operator_id=current_user.id,
            description=log_data.get("description"),
            original_text=log_data.get("text"),
            parsed_data=str(log_data)
        )
        
        db.add(issue_report)
        await db.commit()
        await db.refresh(issue_report)
        
        return {"message": "Issue reported successfully", "report_id": issue_report.id}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reporting issue: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# Sandbox read endpoint (no auth)
# ---------------------------------------------------------------------------

def _initials(name: str) -> str:
    parts = name.split()
    return (parts[0][0] + parts[1][0]).upper() if len(parts) >= 2 else name[:2].upper()


_INTENT_TAG_CLASS = {
    "fuel_log":       "tag-fuel",
    "hours_log":      "tag-hours",
    "issue_report":   "tag-issue",
    "parts_request":  "tag-parts",
    "production_log": "tag-prod",
    "shift_start":    "tag-intent",
    "shift_end":      "tag-intent",
}

_AV_CLASSES = ["av-a", "av-b", "av-c", "av-d", "av-a"]


@logs_router.get("/events")
async def all_events(limit: int = 100, db: AsyncSession = Depends(get_db)):
    """
    All timeline events from today (most recent first optional).
    Powers the Event Log panel in the owner screen.
    """
    rows = (await db.execute(
        select(TimelineEvent, Machine, User)
        .join(Machine, Machine.id == TimelineEvent.machine_id)
        .outerjoin(User, User.id == TimelineEvent.operator_id)
        .order_by(TimelineEvent.created_at.desc())
        .limit(limit)
    )).all()
    rows = list(reversed(rows))

    # Stable av-class per operator
    op_class_map: dict[int, str] = {}
    class_idx = 0

    result = []
    for event, machine, op in rows:
        if op and op.id not in op_class_map:
            op_class_map[op.id] = _AV_CLASSES[class_idx % len(_AV_CLASSES)]
            class_idx += 1

        intent = event.event_type.lower()
        tags = [intent, machine.reg_number]

        # Add notable content fields as extra tags
        if intent == "fuel_log" and event.content.get("fuel_volume"):
            tags.append(f"{int(event.content['fuel_volume'])}л")
        if intent == "hours_log" and event.content.get("hours"):
            tags.append(f"{int(event.content['hours'])}ч")
        if intent == "issue_report":
            sev = event.content.get("severity") or event.content.get("component")
            if sev:
                tags.append(sev)
        if event.content.get("inferred"):
            tags.append("context-inferred")

        severity = ""
        if intent == "issue_report":
            sev_val = (event.content.get("severity") or "").lower()
            severity = "crit" if sev_val == "critical" else ("warn" if sev_val in ("warning", "high") else "")

        extracted: dict = {"Intent": event.event_type}
        if machine:
            extracted["Machine"] = machine.reg_number
        if event.content:
            for k, v in event.content.items():
                if k not in ("inferred",):
                    extracted[k.title()] = str(v)
        if event.confidence:
            extracted["Confidence"] = f"{int(event.confidence * 100)}%"

        result.append({
            "id":               event.id,
            "time":             event.created_at.strftime("%H:%M"),
            "operator_name":    op.name if op else "Unknown",
            "operator_initials": _initials(op.name) if op else "?",
            "operator_av_class": op_class_map.get(op.id, "av-a") if op else "av-a",
            "machine_reg":      machine.reg_number,
            "raw_text":         event.raw_text or "",
            "intent":           intent,
            "severity":         severity,
            "tags":             tags,
            "extracted":        extracted,
            "confidence":       round(event.confidence, 2) if event.confidence else None,
            "created_at":       event.created_at.isoformat(),
        })

    return result
