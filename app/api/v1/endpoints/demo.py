"""
app/api/v1/endpoints/demo.py

Sandbox seed/reset endpoints.

  POST /api/v1/demo/seed   — insert demo fleet data (idempotent)
  DELETE /api/v1/demo/reset — wipe all data and re-seed
"""

from __future__ import annotations

from datetime import date, datetime, time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models import (
    ActiveSession, FuelLog, HoursLog, IssueReport,
    Machine, MachineAssignment, MachineState,
    TimelineEvent, User,
)

router = APIRouter(prefix="/demo", tags=["Demo"])

SEED_OWNER_MOBILE = "+79990000000"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dt(h: int, m: int) -> datetime:
    return datetime.combine(date.today(), time(h, m))


async def _is_seeded(db: AsyncSession) -> bool:
    from sqlalchemy import select
    result = await db.execute(
        select(User).where(User.mobile == SEED_OWNER_MOBILE, User.user_type == "OWNER")
    )
    return result.scalar_one_or_none() is not None


async def _wipe(db: AsyncSession) -> None:
    for table in [
        "active_sessions", "machine_states",
        "fuel_logs", "hours_logs", "issue_reports",
        "timeline_events", "activity_logs",
        "machine_assignments", "machines", "users",
    ]:
        await db.execute(text(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE"))
    await db.commit()


async def _seed(db: AsyncSession) -> dict:
    # ── 1. Owner ──────────────────────────────────────────────────────────
    owner = User(
        platform_user_id=9999, mobile=SEED_OWNER_MOBILE,
        name="Алексей Петров", company_name="СтройТех ООО", user_type="OWNER",
    )
    db.add(owner)
    await db.flush()

    # ── 2. Operators ──────────────────────────────────────────────────────
    ivan    = User(platform_user_id=1001, mobile="+79991111111", name="Иван Сидоров",    user_type="OPERATOR", owner_id=owner.id)
    petr    = User(platform_user_id=1002, mobile="+79992222222", name="Пётр Кузнецов",   user_type="OPERATOR", owner_id=owner.id)
    mikhail = User(platform_user_id=1003, mobile="+79993333333", name="Михаил Фёдоров",  user_type="OPERATOR", owner_id=owner.id)
    sergey  = User(platform_user_id=1004, mobile="+79994444444", name="Сергей Власов",   user_type="OPERATOR", owner_id=owner.id)
    for op in [ivan, petr, mikhail, sergey]:
        db.add(op)
    await db.flush()

    # ── 3. Machines ───────────────────────────────────────────────────────
    # reg_number: real GOST 3207-77 plates (placeholder values for demo)
    # alias:      crew callsign / display name used in operator messages
    cat101 = Machine(reg_number="А771МР77", alias="КАТ-101",  machine_type="Экскаватор",  model="Caterpillar 320D", year=2019, owner_id=owner.id)
    blz042 = Machine(reg_number="В042СА77", alias="БЛЗ-042",  machine_type="Самосвал",    model="БелАЗ 75131",      year=2020, owner_id=owner.id)
    kom007 = Machine(reg_number="К007МН77", alias="КОМ-007",  machine_type="Бульдозер",   model="Komatsu D155AX",   year=2018, owner_id=owner.id)
    grd003 = Machine(reg_number="Е003ВТ77", alias="ГРД-003",  machine_type="Грейдер",     model="ВГМТ 14ГМ",        year=2021, owner_id=owner.id)
    krn005 = Machine(reg_number="Н005КО77", alias="КРН-005",  machine_type="Кран",        model="Liebherr LTM 1100",year=2017, owner_id=owner.id)
    for m in [cat101, blz042, kom007, grd003, krn005]:
        db.add(m)
    await db.flush()

    # ── 4. Assignments ────────────────────────────────────────────────────
    db.add(MachineAssignment(machine_id=cat101.id, operator_id=ivan.id,    is_active=True,  assigned_at=_dt(7, 0)))
    db.add(MachineAssignment(machine_id=blz042.id, operator_id=petr.id,    is_active=True,  assigned_at=_dt(7, 0)))
    db.add(MachineAssignment(machine_id=blz042.id, operator_id=ivan.id,    is_active=False, assigned_at=_dt(6, 0), unassigned_at=_dt(7, 0)))
    db.add(MachineAssignment(machine_id=kom007.id, operator_id=mikhail.id, is_active=True,  assigned_at=_dt(7, 0)))
    db.add(MachineAssignment(machine_id=grd003.id, operator_id=sergey.id,  is_active=True,  assigned_at=_dt(7, 0)))
    db.add(MachineAssignment(machine_id=krn005.id, operator_id=sergey.id,  is_active=True,  assigned_at=_dt(7, 0)))
    await db.flush()

    # ── 5. Timeline events ────────────────────────────────────────────────
    e1  = TimelineEvent(machine_id=cat101.id, operator_id=ivan.id,    event_type="SHIFT_START",    content={"reg_number": "А771МР77", "alias": "КАТ-101"},                                  raw_text="Начинаю смену на КАТ-101",          confidence=0.97, via_llm=True, created_at=_dt(7, 2))
    e2  = TimelineEvent(machine_id=blz042.id, operator_id=petr.id,    event_type="SHIFT_START",    content={"reg_number": "В042СА77", "alias": "БЛЗ-042"},                                  raw_text="Начинаю смену на БЛЗ-042",          confidence=0.97, via_llm=True, created_at=_dt(7, 10))
    e3  = TimelineEvent(machine_id=kom007.id, operator_id=mikhail.id, event_type="SHIFT_START",    content={"reg_number": "К007МН77", "alias": "КОМ-007"},                                  raw_text="начинаю КОМ-007",                   confidence=0.95, via_llm=True, created_at=_dt(7, 30))
    e4  = TimelineEvent(machine_id=blz042.id, operator_id=petr.id,    event_type="FUEL_LOG",       content={"fuel_volume": 80,  "unit": "л"},                                              raw_text="Залил 80л солярки",                 confidence=0.93, via_llm=True, created_at=_dt(8, 0))
    e5  = TimelineEvent(machine_id=cat101.id, operator_id=ivan.id,    event_type="FUEL_LOG",       content={"fuel_volume": 150, "unit": "л"},                                              raw_text="Залил 150 литров",                  confidence=0.96, via_llm=True, created_at=_dt(8, 15))
    e6  = TimelineEvent(machine_id=cat101.id, operator_id=ivan.id,    event_type="HOURS_LOG",      content={"hours": 6},                                                                   raw_text="Наработка 6 часов",                 confidence=0.94, via_llm=True, created_at=_dt(9, 30))
    e7  = TimelineEvent(machine_id=blz042.id, operator_id=petr.id,    event_type="ISSUE_REPORT",   content={"description": "Гидравлика не поднимает кузов", "component": "hydraulics", "severity": "warning"}, raw_text="Гидравлика не поднимает кузов",     confidence=0.88, via_llm=True, created_at=_dt(9, 47))
    e8  = TimelineEvent(machine_id=blz042.id, operator_id=petr.id,    event_type="STATUS_UPDATE",  content={"context": "Стоим, началось после загрузки"},                                  raw_text="Стоим, началось после загрузки",    confidence=0.91, via_llm=True, created_at=_dt(9, 49))
    e9  = TimelineEvent(machine_id=cat101.id, operator_id=ivan.id,    event_type="PRODUCTION_LOG", content={"qty": 18, "unit": "кубов"},                                                   raw_text="Вывезли 18 кубов грунта",           confidence=0.92, via_llm=True, created_at=_dt(10, 5))
    e10 = TimelineEvent(machine_id=kom007.id, operator_id=mikhail.id, event_type="PARTS_REQUEST",  content={"part": "hydraulic filter"},                                                   raw_text="Нужен фильтр гидравлический",       confidence=0.92, via_llm=True, created_at=_dt(10, 15))
    e11 = TimelineEvent(machine_id=cat101.id, operator_id=ivan.id,    event_type="FUEL_LOG",       content={"fuel_volume": 50, "unit": "л", "inferred": True},                             raw_text="ещё 50 залил",                      confidence=0.87, via_llm=True, created_at=_dt(10, 30))
    e12 = TimelineEvent(machine_id=kom007.id, operator_id=mikhail.id, event_type="HOURS_LOG",      content={"hours": 3},                                                                   raw_text="Наработка 3 часа",                  confidence=0.94, via_llm=True, created_at=_dt(11, 10))

    for e in [e1, e2, e3, e4, e5, e6, e7, e8, e9, e10, e11, e12]:
        db.add(e)
    await db.flush()

    # ── 6. Specific log tables ────────────────────────────────────────────
    db.add(FuelLog(machine_id=blz042.id, operator_id=petr.id,  fuel_volume=80,  unit="л", original_text="Залил 80л солярки",   parsed_data='{"fuel_volume":80}',  timeline_event_id=e4.id,  created_at=_dt(8, 0)))
    db.add(FuelLog(machine_id=cat101.id, operator_id=ivan.id,  fuel_volume=150, unit="л", original_text="Залил 150 литров",    parsed_data='{"fuel_volume":150}', timeline_event_id=e5.id,  created_at=_dt(8, 15)))
    db.add(FuelLog(machine_id=cat101.id, operator_id=ivan.id,  fuel_volume=50,  unit="л", original_text="ещё 50 залил",        parsed_data='{"fuel_volume":50}',  timeline_event_id=e11.id, created_at=_dt(10, 30)))

    db.add(HoursLog(machine_id=cat101.id, operator_id=ivan.id,    hours=6, unit="ч", original_text="Наработка 6 часов", parsed_data='{"hours":6}', timeline_event_id=e6.id,  created_at=_dt(9, 30)))
    db.add(HoursLog(machine_id=kom007.id, operator_id=mikhail.id, hours=3, unit="ч", original_text="Наработка 3 часа",  parsed_data='{"hours":3}', timeline_event_id=e12.id, created_at=_dt(11, 10)))

    db.add(IssueReport(machine_id=blz042.id, operator_id=petr.id, description="Гидравлика не поднимает кузов", status="REPORTED", priority="MEDIUM", original_text="Гидравлика не поднимает кузов", parsed_data='{"component":"hydraulics","severity":"warning"}', timeline_event_id=e7.id, created_at=_dt(9, 47)))

    # ── 7. Active sessions ────────────────────────────────────────────────
    db.add(ActiveSession(operator_id=ivan.id,    machine_id=cat101.id, shift_state="ACTIVE", started_at=_dt(7, 2),  last_seen_at=_dt(10, 30), fuel_logged_this_shift=200, hours_logged_this_shift=6, checkin_count=4))
    db.add(ActiveSession(operator_id=petr.id,    machine_id=blz042.id, shift_state="ACTIVE", started_at=_dt(7, 10), last_seen_at=_dt(9, 49),  fuel_logged_this_shift=80,  hours_logged_this_shift=3, checkin_count=2))
    db.add(ActiveSession(operator_id=mikhail.id, machine_id=kom007.id, shift_state="ACTIVE", started_at=_dt(7, 30), last_seen_at=_dt(11, 10), fuel_logged_this_shift=0,   hours_logged_this_shift=3, checkin_count=2))

    # ── 8. Machine states ─────────────────────────────────────────────────
    db.add(MachineState(machine_id=cat101.id, status="WORKING", active_operator_id=ivan.id,    last_known_fuel_liters=50,  last_known_hours=6, fuel_added_today=200, hours_worked_today=6, open_issue_count=0, shift_started_at=_dt(7, 2),  last_event_at=_dt(10, 30)))
    db.add(MachineState(machine_id=blz042.id, status="WARNING", active_operator_id=petr.id,    last_known_fuel_liters=80,  last_known_hours=0, fuel_added_today=80,  hours_worked_today=3, open_issue_count=1, shift_started_at=_dt(7, 10), last_event_at=_dt(9, 49)))
    db.add(MachineState(machine_id=kom007.id, status="WORKING", active_operator_id=mikhail.id, last_known_fuel_liters=None,last_known_hours=3, fuel_added_today=0,   hours_worked_today=3, open_issue_count=0, shift_started_at=_dt(7, 30), last_event_at=_dt(11, 10)))
    db.add(MachineState(machine_id=grd003.id, status="IDLE",    fuel_added_today=0, hours_worked_today=0, open_issue_count=0))
    db.add(MachineState(machine_id=krn005.id, status="IDLE",    fuel_added_today=0, hours_worked_today=0, open_issue_count=0))

    await db.commit()

    return {
        "seeded": True,
        "owner": owner.name,
        "operators": 4,
        "machines": 5,
        "timeline_events": 12,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.delete("/wipe")
async def wipe_demo(db: AsyncSession = Depends(get_db)):
    """Wipe all data without re-seeding. Use before running setup.sh for a clean slate."""
    await _wipe(db)
    return {"wiped": True}


@router.post("/seed")
async def seed_demo(db: AsyncSession = Depends(get_db)):
    """Insert sandbox fleet data. Safe to call multiple times — skips if already seeded."""
    if await _is_seeded(db):
        return {"seeded": False, "message": "Already seeded — call DELETE /demo/reset to re-seed"}
    return await _seed(db)


@router.delete("/reset")
async def reset_demo(db: AsyncSession = Depends(get_db)):
    """Wipe all data and re-seed the sandbox."""
    await _wipe(db)
    result = await _seed(db)
    result["reset"] = True
    return result
