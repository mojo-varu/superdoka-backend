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

owner_router = APIRouter(tags=["Owner Operations"])

class MachineCreate(BaseModel):
    machine_type: str = Field(..., example="экскаватор")
    model: str = Field(..., example="Caterpillar 320D")
    year: int = Field(..., ge=1900, le=2030, example=2018)
    reg_number: str = Field(..., example="А771МР77")
    serial_number: Optional[str] = None
    notes: Optional[str] = None

class MachineResponse(BaseModel):
    id: int
    reg_number: str
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
    operator_name: str = Field(..., example="Андрей")
    contact: str = Field(..., example="79992348765")
    company_name: Optional[str] = None

class OperatorResponse(BaseModel):
    id: int
    name: str
    mobile: str
    company_name: Optional[str] = None
    is_active: bool
    created_at: datetime
    telegram_id: Optional[int] = None

    class Config:
        from_attributes = True

class AssignmentCreate(BaseModel):
    reg_number: str = Field(..., example="А771МР77")
    operator_contact: str = Field(..., example="79992348765")

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
    telegram_id: Optional[int] = None

class OwnerRegisterResponse(BaseModel):
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
            telegram_id=request.telegram_id,
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
#     telegram_id: Optional[int] = None,
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
#             telegram_id=telegram_id,
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
        # Check if machine with reg_number already exists
        existing = await db.execute(
            select(Machine).where(Machine.reg_number == machine.reg_number)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Machine with this registration number already exists")
        
        # Create machine
        db_machine = Machine(
            reg_number=machine.reg_number,
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
        
        # Log activity
        activity = ActivityLog(
            user_id=current_user.id,
            action="MACHINE_ADDED",
            entity_type="MACHINE",
            entity_id=db_machine.id,
            details=f"Added machine {machine.reg_number} - {machine.model}"
        )
        db.add(activity)
        await db.commit()
        
        return db_machine
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding machine: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

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
                    User.mobile == operator.contact,
                    User.owner_id == current_user.id,
                    User.user_type == UserTypeEnum.OPERATOR.value
                )
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Operator already exists for this owner")
        
        # Create operator
        db_operator = User(
            name=operator.operator_name,
            mobile=operator.contact,
            company_name=operator.company_name,
            user_type=UserTypeEnum.OPERATOR.value,
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
            details=f"Added operator {operator.operator_name} with contact {operator.contact}"
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
                User.user_type == UserTypeEnum.OPERATOR.value,
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
    """Assign operator to machine and generate Telegram link"""
    try:
        # Get machine
        machine_result = await db.execute(
            select(Machine).where(
                and_(
                    Machine.reg_number == assignment.reg_number,
                    Machine.owner_id == current_user.id,
                    Machine.is_active == True
                )
            )
        )
        machine = machine_result.scalar_one_or_none()
        if not machine:
            raise HTTPException(status_code=404, detail="Machine not found")
        
        # Get operator
        operator_result = await db.execute(
            select(User).where(
                and_(
                    User.mobile == assignment.operator_contact,
                    User.owner_id == current_user.id,
                    User.user_type == UserTypeEnum.OPERATOR.value,
                    User.is_active == True
                )
            )
        )
        operator = operator_result.scalar_one_or_none()
        if not operator:
            raise HTTPException(status_code=404, detail="Operator not found")
        
        # Check if machine is already assigned
        existing_assignment = await db.execute(
            select(MachineAssignment).where(
                and_(
                    MachineAssignment.machine_id == machine.id,
                    MachineAssignment.is_active == True
                )
            )
        )
        if existing_assignment.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Machine is already assigned to an operator")
        
        # Create assignment
        db_assignment = MachineAssignment(
            machine_id=machine.id,
            operator_id=operator.id,
            is_active=True
        )
        
        db.add(db_assignment)
        await db.commit()
        await db.refresh(db_assignment)
        
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


from app.core.ner_handler import NERHandler, init_model, is_model_ready, model_load_error, post_process_ner
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
