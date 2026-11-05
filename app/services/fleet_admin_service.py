"""
app/services/fleet_admin_service.py

SPEC-001-R05/R06/R13: owner-driven fleet admin (add machine, add operator,
operator invite), shared by both the REST endpoints
(app/api/v1/endpoints/owners.py) and the bot's /addmachine, /addoperator
commands (app/services/engine_entrypoint.py) so the logic exists exactly
once.

Engine-side module — no Telegram/aiogram or app/channels imports (ADR-0020).
"""
from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DEFAULT_ORG_ID, Invite, Machine, MachineAssignment, User

# GOST 3207-77: [АВЕКМНОРСТУХ] + 3 digits + 2 letters + 2-3 digit region code.
# Single source — app/api/v1/endpoints/owners.py's MachineCreate.reg_number
# Field imports this instead of duplicating the pattern string.
REG_NUMBER_PATTERN = r"^[АВЕКМНОРСТУХ]\d{3}[АВЕКМНОРСТУХ]{2}\d{2,3}$"

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


class MachineOutcome(str, Enum):
    CREATED = "created"
    DUPLICATE_REG_NUMBER = "duplicate_reg_number"
    DUPLICATE_ALIAS = "duplicate_alias"


@dataclass
class MachineResult:
    outcome: MachineOutcome
    machine: Optional[Machine] = None


async def add_machine(
    db: AsyncSession,
    owner: User,
    reg_number: str,
    machine_type: str,
    model: str,
    year: int,
    alias: Optional[str] = None,
    serial_number: Optional[str] = None,
    notes: Optional[str] = None,
) -> MachineResult:
    """SPEC-001-R05: duplicate aliases within an org MUST be rejected with a
    clear message. Scoped by Machine.owner_id — the REST layer's actual
    tenancy boundary today (org_id exists on the column but isn't yet the
    operative scope anywhere else in this codebase)."""
    resolved_alias = alias or _derive_alias(machine_type, reg_number)

    existing_alias = (await db.execute(
        select(Machine).where(
            Machine.owner_id == owner.id,
            Machine.alias == resolved_alias,
        )
    )).scalar_one_or_none()
    if existing_alias is not None:
        return MachineResult(MachineOutcome.DUPLICATE_ALIAS)

    db_machine = Machine(
        reg_number=reg_number,
        alias=resolved_alias,
        machine_type=machine_type,
        model=model,
        year=year,
        owner_id=owner.id,
        serial_number=serial_number,
        notes=notes,
    )
    db.add(db_machine)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return MachineResult(MachineOutcome.DUPLICATE_REG_NUMBER)
    await db.refresh(db_machine)
    return MachineResult(MachineOutcome.CREATED, db_machine)


class OperatorOutcome(str, Enum):
    CREATED = "created"
    DUPLICATE = "duplicate"


@dataclass
class OperatorResult:
    outcome: OperatorOutcome
    operator: Optional[User] = None


async def add_operator(db: AsyncSession, owner: User, name: str, mobile: str) -> OperatorResult:
    """Same dedup semantics as the existing REST add_operator: mobile unique
    per owner among that owner's operators."""
    existing = (await db.execute(
        select(User).where(
            and_(
                User.mobile == mobile,
                User.owner_id == owner.id,
                User.user_type == "OPERATOR",
            )
        )
    )).scalar_one_or_none()
    if existing is not None:
        return OperatorResult(OperatorOutcome.DUPLICATE)

    operator = User(
        name=name,
        mobile=mobile,
        user_type="OPERATOR",
        owner_id=owner.id,
    )
    db.add(operator)
    await db.commit()
    await db.refresh(operator)
    return OperatorResult(OperatorOutcome.CREATED, operator)


async def create_operator_invite(
    db: AsyncSession,
    owner: User,
    operator: User,
    machine_id: Optional[int] = None,
    expiry_hours: int = 72,
) -> Invite:
    """SPEC-001-R06: single-use, expiring (starting value 72 hours).
    bound_user_id points at the pre-created operator row so redemption
    (onboarding_service.bind_invite) attaches platform_user_id to it rather
    than creating a duplicate User."""
    invite = Invite(
        org_id=DEFAULT_ORG_ID,
        token=secrets.token_urlsafe(24),
        role="operator",
        operator_name=operator.name,
        machine_id=machine_id,
        created_by=owner.id,
        bound_user_id=operator.id,
        expires_at=datetime.utcnow() + timedelta(hours=expiry_hours),
    )
    db.add(invite)

    if machine_id is not None:
        # Matches today's external behaviour: the assignment exists at
        # invite time, not at redemption time. Skip quietly if it already
        # exists (uq_assignment_operator_machine) rather than erroring.
        existing_assignment = (await db.execute(
            select(MachineAssignment).where(
                MachineAssignment.machine_id == machine_id,
                MachineAssignment.operator_id == operator.id,
            )
        )).scalar_one_or_none()
        if existing_assignment is None:
            db.add(MachineAssignment(machine_id=machine_id, operator_id=operator.id))

    await db.commit()
    await db.refresh(invite)
    return invite


def build_invite_link(bot_username: str, token: str) -> str:
    return f"https://t.me/{bot_username}?start={token}"


class AssignOutcome(str, Enum):
    ASSIGNED = "assigned"
    ALREADY_ASSIGNED = "already_assigned"
    MACHINE_NOT_FOUND = "machine_not_found"


async def find_machine_by_alias(db: AsyncSession, owner: User, alias: str) -> Optional[Machine]:
    return (await db.execute(
        select(Machine).where(
            Machine.owner_id == owner.id,
            Machine.alias == alias,
        )
    )).scalar_one_or_none()
