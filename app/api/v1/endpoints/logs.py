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
from app.db.models import User, Machine, MachineAssignment, FuelLog, HoursLog, IssueReport, ActivityLog
from app.api.deps import get_any_telegram_user, require_owner

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
    current_user: User = Depends(get_any_telegram_user()),
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
    current_user: User = Depends(get_any_telegram_user()),
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
    current_user: User = Depends(get_any_telegram_user()),
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
