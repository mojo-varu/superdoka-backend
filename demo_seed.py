#!/usr/bin/env python3
"""
demo_seed.py
============
Populates the VFM database with realistic demo data for the capability
demonstration. Run once before starting the backend.

Creates:
  - 1 owner account  (Алексей Петров, owner ID visible in demo UI)
  - 3 operators      (Иван, Пётр, Михаил — each with a REST-accessible ID)
  - 3 machines       (CAT-101 Экскаватор, BLZ-042 Самосвал, KOM-007 Бульдозер)
  - Seeded timeline  (yesterday's shift events so the UI has history to show)

Usage:
  python demo_seed.py                        # uses DATABASE_URL from .env
  DATABASE_URL=sqlite+aiosqlite:///./x.db python demo_seed.py
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta

# Load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./vfm_dev.db")

from app.db.database import init_db, AsyncSessionLocal
from app.db.models import (
    FuelLog, HoursLog, IssueReport, Machine, MachineState,
    TimelineEvent, User,
)


MACHINES = [
    {"reg_number": "CAT-101", "machine_type": "Экскаватор",
     "model": "Caterpillar 320D", "year": 2019},
    {"reg_number": "BLZ-042", "machine_type": "Самосвал",
     "model": "БелАЗ 75131",    "year": 2020},
    {"reg_number": "KOM-007", "machine_type": "Бульдозер",
     "model": "Komatsu D155AX", "year": 2018},
]

OPERATORS = [
    {"platform_user_id": 200001, "name": "Иван Сидоров",   "mobile": "+79001234501"},
    {"platform_user_id": 200002, "name": "Пётр Кузнецов",  "mobile": "+79001234502"},
    {"platform_user_id": 200003, "name": "Михаил Фёдоров", "mobile": "+79001234503"},
]


async def seed():
    await init_db()
    async with AsyncSessionLocal() as db:
        # ── Owner ──────────────────────────────────────────────────────────
        owner = User(
            platform_user_id=100001, mobile="+79000000001",
            name="Алексей Петров", user_type="OWNER",
        )
        db.add(owner)
        await db.flush()

        # ── Operators ─────────────────────────────────────────────────────
        ops = []
        for op_data in OPERATORS:
            op = User(**op_data, user_type="OPERATOR", owner_id=owner.id)
            db.add(op)
            ops.append(op)
        await db.flush()

        # ── Machines + MachineState ────────────────────────────────────────
        machines = []
        for m_data in MACHINES:
            m = Machine(**m_data, owner_id=owner.id)
            db.add(m)
            await db.flush()
            state = MachineState(
                machine_id=m.id,
                status="WORKING",
                fuel_added_today=0.0,
                hours_worked_today=0.0,
                open_issue_count=0,
            )
            db.add(state)
            machines.append(m)
        await db.flush()

        # ── Yesterday's shift history (CAT-101, Иван) ─────────────────────
        # Seeds the UI timeline so it shows real data immediately
        cat = machines[0]
        ivan = ops[0]
        yesterday = datetime.utcnow() - timedelta(days=1)

        history = [
            # (event_type, content, raw_text, hour_offset)
            ("SHIFT_START",  {"reg_number": "CAT-101"},                         "Начинаю смену на CAT-101",          0),
            ("FUEL_LOG",     {"fuel_volume": 150.0, "unit": "литров"},          "Залил 150 литров",                   1),
            ("HOURS_LOG",    {"hours": 4.0,  "unit": "часов"},                  "Наработка 4 часа",                   5),
            ("ISSUE_REPORT", {"description": "течь масла у гидравлики",
                              "component": "hydraulics", "severity": "warning"}, "Небольшая течь масла у гидравлики",  6),
            ("FUEL_LOG",     {"fuel_volume": 80.0, "unit": "литров"},           "Ещё 80 литров залил",                7),
            ("HOURS_LOG",    {"hours": 3.0,  "unit": "часов"},                  "Ещё 3 часа наработки",               8),
            ("SHIFT_END",    {"fuel_total": 230.0, "hours_total": 7.0},         "Смена закончена",                   10),
        ]
        for ev_type, content, raw, h_offset in history:
            ev = TimelineEvent(
                machine_id  = cat.id,
                operator_id = ivan.id,
                event_type  = ev_type,
                content     = content,
                raw_text    = raw,
                source      = "rest",
                confidence  = 0.94,
                via_llm     = True,
                created_at  = yesterday.replace(hour=6) + timedelta(hours=h_offset),
            )
            db.add(ev)

            # Write specific log tables too
            if ev_type == "FUEL_LOG":
                db.add(FuelLog(
                    machine_id=cat.id, operator_id=ivan.id,
                    fuel_volume=content["fuel_volume"], unit="литров",
                    original_text=raw,
                ))
            elif ev_type == "HOURS_LOG":
                db.add(HoursLog(
                    machine_id=cat.id, operator_id=ivan.id,
                    hours=content["hours"], unit="часов",
                    original_text=raw,
                ))
            elif ev_type == "ISSUE_REPORT":
                db.add(IssueReport(
                    machine_id=cat.id, operator_id=ivan.id,
                    description=content["description"],
                    status="REPORTED", priority="MEDIUM",
                    original_text=raw,
                ))

        # Update CAT-101 state to reflect yesterday's shift
        for state in [s for s in (await db.execute(
            __import__("sqlalchemy", fromlist=["select"]).select(MachineState)
            .where(MachineState.machine_id == cat.id)
        )).scalars().all()]:
            state.fuel_added_today   = 230.0
            state.hours_worked_today = 7.0
            state.open_issue_count   = 1
            state.last_event_at      = yesterday.replace(hour=16)

        await db.commit()

    print("\nDemo seed complete.")
    print(f"  Owner:      Алексей Петров    (telegram_id=100001)")
    for i, op in enumerate(OPERATORS):
        print(f"  Operator {i+1}: {op['name']:<20} (operator_id={op['platform_user_id']})")
    for m in MACHINES:
        print(f"  Machine:    {m['reg_number']:<10} {m['machine_type']}")
    print()
    print("Use these telegram_ids in the demo UI to send messages as each operator.")
    print("Machine CAT-101 has yesterday's shift pre-loaded.")


if __name__ == "__main__":
    asyncio.run(seed())
