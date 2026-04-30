from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from datetime import datetime, timedelta
import logging
import re
import secrets
import string
from enum import Enum

# Import your existing dependencies
from app.db.database import get_db
from app.db.models import (
    User, Machine, MachineAssignment, FuelLog, HoursLog, IssueReport,
    ActivityLog, ActiveSession, MachineState, TimelineEvent,
)
from app.api.deps import get_any_platform_user, require_owner

logger = logging.getLogger(__name__)

owner_router = APIRouter(tags=["Owner Operations"])

_MACHINE_TYPE_ABBREV: dict[str, str] = {
    "экскаватор": "ЭКС",
    "самосвал":   "САМ",
    "бульдозер":  "БУЛ",
    "грейдер":    "ГРД",
    "кран":       "КРН",
    "погрузчик":  "ПГР",
    "каток":      "КАТ",
    "трактор":    "ТРК",
    "автогрейдер": "АГР",
    "скрепер":    "СКР",
}

def _derive_alias(machine_type: str, reg_number: str) -> str:
    abbrev = _MACHINE_TYPE_ABBREV.get(machine_type.lower(), machine_type[:3].upper())
    # extract trailing region digits (2-3 chars at end of GOST plate)
    m = re.search(r"\d{2,3}$", reg_number)
    suffix = m.group() if m else reg_number[-3:]
    return f"{abbrev}-{suffix}"


class MachineCreate(BaseModel):
    machine_type: str = Field(..., example="экскаватор")
    model: str = Field(..., example="Caterpillar 320D")
    year: int = Field(..., ge=1900, le=2030, example=2018)
    # GOST 3207-77: [АВЕКМНОРСТУХ] + 3 digits + 2 letters + 2–3 digit region code
    reg_number: str = Field(
        ...,
        pattern=r"^[АВЕКМНОРСТУХ]\d{3}[АВЕКМНОРСТУХ]{2}\d{2,3}$",
        example="А771МР77",
    )
    alias: Optional[str] = Field(None, max_length=50, example="КАТ-101")
    serial_number: Optional[str] = None
    notes: Optional[str] = None

class MachineResponse(BaseModel):
    id: int
    reg_number: str
    alias: Optional[str] = None
    machine_type: str
    model: str
    year: int
    is_active: bool
    created_at: datetime
    serial_number: Optional[str] = None
    notes: Optional[str] = None

    class Config:
        from_attributes = True

class OperatorCreate(BaseModel):
    name: str = Field(..., example="Андрей Иванов")
    mobile: str = Field(..., example="+79992348765")
    platform_user_id: Optional[int] = None
    company_name: Optional[str] = None

class OperatorResponse(BaseModel):
    id: int
    name: str
    mobile: str
    company_name: Optional[str] = None
    is_active: bool
    created_at: datetime
    platform_user_id: Optional[int] = None

    class Config:
        from_attributes = True

class AssignmentCreate(BaseModel):
    operator_id: int
    machine_id: int

class AssignmentResponse(BaseModel):
    id: int
    machine_reg_number: str
    operator_name: str
    operator_contact: str
    assigned_at: datetime
    is_active: bool
    telegram_link_token: Optional[str] = None
    telegram_link_expires_at: Optional[datetime] = None

class OperatorLinkResponse(BaseModel):
    telegram_link: str
    expires_at: datetime
    token: str

# Link Generator Class
class MachineOperatorLinkGenerator:
    BOT_USERNAME = "machine_management_bot"  # Replace with your actual bot username

    @staticmethod
    def generate_token(length: int = 32) -> str:
        """Generate secure random token"""
        alphabet = string.ascii_letters + string.digits
        return ''.join(secrets.choice(alphabet) for _ in range(length))

    @staticmethod
    async def generate_operator_link(
        assignment: MachineAssignment,
        db: AsyncSession,
        expiry_hours: int = 24
    ) -> str:
        """Generate telegram link for operator onboarding"""
        try:
            # Generate token and expiry
            token = MachineOperatorLinkGenerator.generate_token()
            expires_at = datetime.utcnow() + timedelta(hours=expiry_hours)
            
            # Update assignment with token
            assignment.telegram_link_token = token
            assignment.telegram_link_expires_at = expires_at
            await db.commit()
            
            # Build telegram link
            start_param = f"operator_{assignment.id}_AUTH_{token}"
            link = f"https://t.me/{MachineOperatorLinkGenerator.BOT_USERNAME}?start={start_param}"
            
            logger.info(f"Generated operator link for assignment {assignment.id}")
            return link
            
        except Exception as e:
            logger.error(f"Failed to generate operator link: {str(e)}")
            raise

class OwnerRegisterRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    mobile: str = Field(..., min_length=10, max_length=20)
    company_name: Optional[str] = Field(None, max_length=100)
    platform_user_id: Optional[int] = None

class OwnerRegisterResponse(BaseModel):
    id: int
    message: str
    owner_id: str

# app/api/v1/endpoints/owners.py
# from app.api.v1.endpoints.schemas import OwnerRegisterRequest, OwnerRegisterResponse

@owner_router.post("/register", response_model=OwnerRegisterResponse)
async def register_owner(
    request: OwnerRegisterRequest,  # Changed to accept Pydantic model
    db: AsyncSession = Depends(get_db)
):
    """Register new owner"""
    try:
        # Check if owner already exists
        existing = await db.execute(
            select(User).where(
                and_(
                    User.mobile == request.mobile,
                    User.user_type == "OWNER"
                )
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Owner already registered with this mobile")
        
        # Create owner
        owner = User(
            name=request.name,
            mobile=request.mobile,
            company_name=request.company_name,
            user_type="OWNER",
            platform_user_id=request.platform_user_id,
            owner_id=None
        )
        
        db.add(owner)
        await db.commit()
        await db.refresh(owner)
        
        # Log activity
        activity = ActivityLog(
            user_id=owner.id,
            action="OWNER_REGISTERED",
            entity_type="USER",
            entity_id=owner.id,
            details=f"Owner {request.name} registered with mobile {request.mobile}"
        )
        db.add(activity)
        await db.commit()
        
        return OwnerRegisterResponse(
            id=owner.id,
            message="Owner registered successfully",
            owner_id=str(owner.id)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error registering owner: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")
# Owner Operations
# @owner_router.post("/register", response_model=Dict[str, str])
# async def register_owner(
#     name: str,
#     mobile: str,
#     company_name: Optional[str] = None,
#     platform_user_id: Optional[int] = None,
#     db: AsyncSession = Depends(get_db)
# ):
#     """Register new owner"""
#     try:
#         # Check if owner already exists
#         existing = await db.execute(
#             select(User).where(
#                 and_(
#                     User.mobile == mobile,
#                     User.user_type == UserTypeEnum.OWNER.value
#                 )
#             )
#         )
#         if existing.scalar_one_or_none():
#             raise HTTPException(status_code=400, detail="Owner already registered with this mobile")
        
#         # Create owner
#         owner = User(
#             name=name,
#             mobile=mobile,
#             company_name=company_name,
#             user_type=UserTypeEnum.OWNER.value,
#             platform_user_id=platform_user_id,
#             owner_id=None
#         )
        
#         db.add(owner)
#         await db.commit()
#         await db.refresh(owner)
        
#         # Log activity
#         activity = ActivityLog(
#             user_id=owner.id,
#             action="OWNER_REGISTERED",
#             entity_type="USER",
#             entity_id=owner.id,
#             details=f"Owner {name} registered with mobile {mobile}"
#         )
#         db.add(activity)
#         await db.commit()
        
#         return {"message": "Owner registered successfully", "owner_id": str(owner.id)}
        
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Error registering owner: {str(e)}")
#         raise HTTPException(status_code=500, detail="Internal server error")


@owner_router.post("/machines", response_model=MachineResponse)
async def add_machine(
    machine: MachineCreate,
    current_user: User = Depends(require_owner()),
    db: AsyncSession = Depends(get_db)
):
    """Add new machine"""
    try:
        resolved_alias = machine.alias or _derive_alias(machine.machine_type, machine.reg_number)
        db_machine = Machine(
            reg_number=machine.reg_number,
            alias=resolved_alias,
            machine_type=machine.machine_type,
            model=machine.model,
            year=machine.year,
            owner_id=current_user.id,
            serial_number=machine.serial_number,
            notes=machine.notes
        )
        db.add(db_machine)
        await db.commit()
        await db.refresh(db_machine)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"Machine '{machine.reg_number}' is already registered"
        )
    except Exception as e:
        await db.rollback()
        logger.error(f"Error adding machine: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

    try:
        activity = ActivityLog(
            user_id=current_user.id,
            action="MACHINE_ADDED",
            entity_type="MACHINE",
            entity_id=db_machine.id,
            details=f"Added machine {machine.reg_number} - {machine.model}"
        )
        db.add(activity)
        await db.commit()
    except Exception as e:
        logger.error(f"Error logging machine activity: {str(e)}")

    return db_machine

@owner_router.get("/machines", response_model=List[MachineResponse])
async def get_machines(
    current_user: User = Depends(require_owner()),
    db: AsyncSession = Depends(get_db)
):
    """Get all owner's machines"""
    result = await db.execute(
        select(Machine).where(
            and_(
                Machine.owner_id == current_user.id,
                Machine.is_active == True
            )
        )
    )
    return result.scalars().all()

@owner_router.post("/operators", response_model=OperatorResponse)
async def add_operator(
    operator: OperatorCreate,
    current_user: User = Depends(require_owner()),
    db: AsyncSession = Depends(get_db)
):
    """Add new operator"""
    try:
        # Check if operator already exists for this owner
        existing = await db.execute(
            select(User).where(
                and_(
                    User.mobile == operator.mobile,
                    User.owner_id == current_user.id,
                    User.user_type == "OPERATOR"
                )
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Operator already exists for this owner")

        # Create operator
        db_operator = User(
            name=operator.name,
            mobile=operator.mobile,
            platform_user_id=operator.platform_user_id,
            company_name=operator.company_name,
            user_type="OPERATOR",
            owner_id=current_user.id
        )
        
        db.add(db_operator)
        await db.commit()
        await db.refresh(db_operator)
        
        # Log activity
        activity = ActivityLog(
            user_id=current_user.id,
            action="OPERATOR_ADDED",
            entity_type="USER",
            entity_id=db_operator.id,
            details=f"Added operator {operator.name} with mobile {operator.mobile}"
        )
        db.add(activity)
        await db.commit()
        
        return db_operator
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding operator: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@owner_router.get("/operators", response_model=List[OperatorResponse])
async def get_operators(
    current_user: User = Depends(require_owner()),
    db: AsyncSession = Depends(get_db)
):
    """Get all owner's operators"""
    result = await db.execute(
        select(User).where(
            and_(
                User.owner_id == current_user.id,
                User.user_type == "OPERATOR",
                User.is_active == True
            )
        )
    )
    return result.scalars().all()

@owner_router.post("/assignments", response_model=OperatorLinkResponse)
async def assign_operator(
    assignment: AssignmentCreate,
    current_user: User = Depends(require_owner()),
    db: AsyncSession = Depends(get_db)
):
    """Assign operator to machine and generate onboarding link"""
    try:
        # Verify machine belongs to this owner
        machine = (await db.execute(
            select(Machine).where(
                Machine.id        == assignment.machine_id,
                Machine.owner_id  == current_user.id,
                Machine.is_active == True,
            )
        )).scalar_one_or_none()
        if not machine:
            raise HTTPException(status_code=404, detail="Machine not found")

        # Verify operator belongs to this owner
        operator = (await db.execute(
            select(User).where(
                User.id        == assignment.operator_id,
                User.owner_id  == current_user.id,
                User.user_type == "OPERATOR",
                User.is_active == True,
            )
        )).scalar_one_or_none()
        if not operator:
            raise HTTPException(status_code=404, detail="Operator not found")

        # Prevent duplicate active assignment for this (operator, machine) pair
        pair_exists = (await db.execute(
            select(MachineAssignment).where(
                MachineAssignment.operator_id == operator.id,
                MachineAssignment.machine_id  == machine.id,
                MachineAssignment.is_active   == True,
            )
        )).scalar_one_or_none()
        if pair_exists:
            raise HTTPException(
                status_code=409,
                detail=f"Operator '{operator.name}' is already assigned to machine '{machine.alias or machine.reg_number}'"
            )

        # Create assignment
        db_assignment = MachineAssignment(
            machine_id=machine.id,
            operator_id=operator.id,
            is_active=True,
        )
        db.add(db_assignment)
        try:
            await db.commit()
            await db.refresh(db_assignment)
        except IntegrityError:
            await db.rollback()
            raise HTTPException(
                status_code=409,
                detail=f"Operator '{operator.name}' is already assigned to machine '{machine.alias or machine.reg_number}'"
            )
        
        # Generate telegram link
        telegram_link = await MachineOperatorLinkGenerator.generate_operator_link(
            db_assignment, db
        )
        
        # Log activity
        activity = ActivityLog(
            user_id=current_user.id,
            action="OPERATOR_ASSIGNED",
            entity_type="ASSIGNMENT",
            entity_id=db_assignment.id,
            details=f"Assigned operator {operator.name} to machine {machine.reg_number}"
        )
        db.add(activity)
        await db.commit()
        
        return OperatorLinkResponse(
            telegram_link=telegram_link,
            expires_at=db_assignment.telegram_link_expires_at,
            token=db_assignment.telegram_link_token
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error assigning operator: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

# Reports and Analytics
# @owner_router.get("/reports/fuel", response_model=List[FuelLogResponse])
# async def get_fuel_reports(
#     machine_reg: Optional[str] = None,
#     days: int = 30,
#     current_user: User = Depends(require_owner()),
#     db: AsyncSession = Depends(get_db)
# ):
#     """Get fuel consumption reports"""
#     query = (
#         select(FuelLog)
#         .join(Machine)
#         .join(User)
#         .where(
#             and_(
#                 Machine.owner_id == current_user.id,
#                 FuelLog.created_at >= datetime.utcnow() - timedelta(days=days)
#             )
#         )
#     )
    
#     if machine_reg:
#         query = query.where(Machine.reg_number == machine_reg)
    
#     result = await db.execute(query)
#     logs = result.scalars().all()
    
#     return [
#         FuelLogResponse(
#             id=log.id,
#             machine_reg_number=log.machine.reg_number,
#             operator_name=log.operator.name,
#             created_at=log.created_at,
#             original_text=log.original_text,
#             fuel_volume=log.fuel_volume,
#             unit=log.unit
#         )
#         for log in logs
#     ]

# @owner_router.get("/reports/hours", response_model=List[HoursLogResponse])
# async def get_hours_reports(
#     machine_reg: Optional[str] = None,
#     days: int = 30,
#     current_user: User = Depends(require_owner()),
#     db: AsyncSession = Depends(get_db)
# ):
#     """Get machine hours reports"""
#     query = (
#         select(HoursLog)
#         .join(Machine)
#         .join(User)
#         .where(
#             and_(
#                 Machine.owner_id == current_user.id,
#                 HoursLog.created_at >= datetime.utcnow() - timedelta(days=days)
#             )
#         )
#     )
    
#     if machine_reg:
#         query = query.where(Machine.reg_number == machine_reg)
    
#     result = await db.execute(query)
#     logs = result.scalars().all()
    
#     return [
#         HoursLogResponse(
#             id=log.id,
#             machine_reg_number=log.machine.reg_number,
#             operator_name=log.operator.name,
#             created_at=log.created_at,
#             original_text=log.original_text,
#             hours=log.hours,
#             unit=log.unit
#         )
#         for log in logs
#     ]

# @owner_router.get("/reports/issues", response_model=List[IssueReportResponse])
# async def get_issue_reports(
#     machine_reg: Optional[str] = None,
#     status: Optional[str] = None,
#     days: int = 30,
#     current_user: User = Depends(require_owner()),
#     db: AsyncSession = Depends(get_db)
# ):
    """Get issue reports"""
    query = (
        select(IssueReport)
        .join(Machine)
        .join(User)
        .where(
            and_(
                Machine.owner_id == current_user.id,
                IssueReport.created_at >= datetime.utcnow() - timedelta(days=days)
            )
        )
    )
    
    if machine_reg:
        query = query.where(Machine.reg_number == machine_reg)
    
    if status:
        query = query.where(IssueReport.status == status)
    
    result = await db.execute(query)
    reports = result.scalars().all()
    
    return [
        IssueReportResponse(
            id=report.id,
            machine_reg_number=report.machine.reg_number,
            operator_name=report.operator.name,
            created_at=report.created_at,
            original_text=report.original_text,
            description=report.description,
            status=report.status,
            priority=report.priority
        )
        for report in reports
    ]


from app.core.ner_handler import NERHandler, is_model_ready, model_load_error, post_process_ner
import traceback



# ================================
# Request model
# ================================
class NERRequest(BaseModel):
    text: str


# ================================
# Dependency
# ================================
def get_handler():
    if not is_model_ready():
        if model_load_error:
            raise HTTPException(status_code=500, detail=f"NER model failed to load: {model_load_error}")
        raise HTTPException(status_code=503, detail="NER model still loading")
    return NERHandler()


# ================================
# POST endpoint
# ================================
@owner_router.post("/extract")
async def extract_entities(request: NERRequest, handler: NERHandler = Depends(get_handler)):
    """
    Extract entities from text and return structured schema based on intent.
    """
    try:
        # 1️⃣ Predict raw NER
        ner_result = handler.predict(request.text)

        # 2️⃣ Post-process to structured schema (Pydantic)
        response = post_process_ner(request.text, ner_result)

        return response
    except Exception as e:
        print(f"❌ NER inference failed: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"NER inference failed: {e}")


# ---------------------------------------------------------------------------
# Sandbox fleet endpoints (no auth — used by owner demo screen)
# ---------------------------------------------------------------------------

@owner_router.get("/fleet/summary")
async def fleet_summary(db: AsyncSession = Depends(get_db)):
    """
    Full fleet overview: all machines with live state + active-shift/issue counts.
    Powers the owner dashboard left nav and top-bar badges.
    """
    rows = (await db.execute(
        select(Machine, MachineState, User)
        .outerjoin(MachineState, MachineState.machine_id == Machine.id)
        .outerjoin(User, User.id == MachineState.active_operator_id)
        .where(Machine.is_active == True)
        .order_by(Machine.reg_number)
    )).all()

    active_shifts = (await db.execute(
        select(ActiveSession).where(ActiveSession.shift_state == "ACTIVE")
    )).scalars().all()

    machines = [
        {
            "id":                   m.id,
            "reg_number":           m.reg_number,
            "alias":                m.alias,
            "machine_type":         m.machine_type,
            "model":                f"{m.model} {m.year}",
            "status":               (state.status if state else "IDLE").lower(),
            "active_operator_name": op.name if op else None,
            "fuel_today":           state.fuel_added_today   if state else 0,
            "hours_today":          state.hours_worked_today if state else 0,
            "open_issues":          state.open_issue_count   if state else 0,
        }
        for m, state, op in rows
    ]

    total_open_issues = sum(m["open_issues"] for m in machines)

    return {
        "active_shifts": len(active_shifts),
        "open_issues":   total_open_issues,
        "machines":      machines,
    }


@owner_router.get("/fleet/{machine_id}")
async def machine_intelligence(machine_id: str, db: AsyncSession = Depends(get_db)):
    """
    Deep machine view: metrics, open issues, today's event log.
    machine_id can be the reg_number (e.g. 'А771МР77'), alias (e.g. 'КАТ-101'), or integer DB id.
    Powers the machine detail panel in the owner screen.
    """
    # Accept reg_number string or integer id
    query = select(Machine)
    try:
        query = query.where(Machine.id == int(machine_id))
    except ValueError:
        query = query.where(Machine.reg_number == machine_id)

    machine = (await db.execute(query)).scalar_one_or_none()
    if not machine:
        raise HTTPException(status_code=404, detail="Machine not found")

    state = (await db.execute(
        select(MachineState).where(MachineState.machine_id == machine.id)
    )).scalar_one_or_none()

    active_op = None
    if state and state.active_operator_id:
        active_op = (await db.execute(
            select(User).where(User.id == state.active_operator_id)
        )).scalar_one_or_none()

    # Open issues
    open_issues_rows = (await db.execute(
        select(IssueReport)
        .where(IssueReport.machine_id == machine.id, IssueReport.status == "REPORTED")
        .order_by(IssueReport.created_at.desc())
    )).scalars().all()

    # Today's timeline
    from datetime import date
    today_start = datetime.combine(date.today(), datetime.min.time())
    timeline_rows = (await db.execute(
        select(TimelineEvent)
        .where(TimelineEvent.machine_id == machine.id, TimelineEvent.created_at >= today_start)
        .order_by(TimelineEvent.created_at)
    )).scalars().all()

    # Production today from PRODUCTION_LOG events
    production_today = sum(
        float(e.content.get("qty", 0))
        for e in timeline_rows
        if e.event_type == "PRODUCTION_LOG"
    )

    _dot = {
        "WORKING": "d-work", "WARNING": "d-warn",
        "DOWN": "d-down",    "IDLE": "d-idle", "MAINTENANCE": "d-idle",
    }
    status = state.status if state else "IDLE"

    return {
        "reg_number":          machine.reg_number,
        "machine_type":        machine.machine_type,
        "model":               f"{machine.model} {machine.year}",
        "status":              status.lower(),
        "status_class":        "sb-warn" if status == "WARNING" else ("sb-idle" if status == "IDLE" else "sb-work"),
        "active_operator_name": active_op.name if active_op else None,
        "metrics": {
            "fuel_today":      state.fuel_added_today   if state else 0,
            "hours_today":     state.hours_worked_today if state else 0,
            "production_today": production_today,
            "open_issues":     state.open_issue_count   if state else 0,
            "fuel_rate":       (
                round((state.fuel_added_today or 0) / state.hours_worked_today, 1)
                if state and state.hours_worked_today else 0
            ),
        },
        "open_issues": [
            {
                "title":    issue.description[:80],
                "meta":     f"{issue.created_at.strftime('%H:%M')} · {active_op.name if active_op else '?'} · {issue.priority}",
                "original": issue.original_text,
            }
            for issue in open_issues_rows
        ],
        "timeline": [
            {
                "time":       e.created_at.strftime("%H:%M"),
                "event_type": e.event_type,
                "raw_text":   e.raw_text or "",
                "extracted":  f"{e.event_type.lower()} · conf {int((e.confidence or 0)*100)}%",
                "dot_class":  _dot.get(status, "d-idle"),
                "content":    e.content,
            }
            for e in timeline_rows
        ],
    }
