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

operator_router = APIRouter(tags=["Operator Operations"])

class PhoneVerificationRequest(BaseModel):
    token: str
    phone: str

# Operator Operations
@operator_router.post("/verify-phone")
async def verify_operator_phone(
    request: PhoneVerificationRequest,
    current_user: User = Depends(get_any_telegram_user()),
    db: AsyncSession = Depends(get_db)
):
    """Verify operator phone number and establish telegram_id mapping"""
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
        
        # Update operator with telegram_id
        assignment.operator.telegram_id = current_user.telegram_id
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
