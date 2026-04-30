"""
demo_seed.py

Seeds the demo DB with:
  - 1 owner  (Владелец)
  - 3 operators
  - 3 machines  (excavator, dump truck, bulldozer)
  - 1 owner_settings row
  - MachineState rows (IDLE) for each machine

Run once:  python demo_seed.py
Safe to re-run — skips if data already exists.
"""

import asyncio
from datetime import datetime
from app.db.database import AsyncSessionLocal, init_db
from app.db.models import (
    User, Machine, MachineAssignment, MachineState,
    OwnerSettings, MachineStatus,
)
from sqlalchemy import select


OWNER = {
    "telegram_id": 100001,
    "mobile":      "+79001000001",
    "name":        "Алексей Петров",
    "company_name":"СтройГрупп ООО",
    "user_type":   "OWNER",
}

OPERATORS = [
    {"telegram_id": 200001, "mobile": "+79002000001", "name": "Иван Сидоров",   "user_type": "OPERATOR"},
    {"telegram_id": 200002, "mobile": "+79002000002", "name": "Пётр Кузнецов",  "user_type": "OPERATOR"},
    {"telegram_id": 200003, "mobile": "+79002000003", "name": "Михаил Фёдоров", "user_type": "OPERATOR"},
]

MACHINES = [
    {"reg_number": "CAT-101", "machine_type": "Экскаватор",  "model": "Caterpillar 320D",  "year": 2019},
    {"reg_number": "BLZ-042", "machine_type": "Самосвал",    "model": "БелАЗ 75131",       "year": 2020},
    {"reg_number": "KOM-007", "machine_type": "Бульдозер",   "model": "Komatsu D155AX",    "year": 2018},
]


async def seed():
    await init_db()

    async with AsyncSessionLocal() as db:
        # Check if already seeded
        result = await db.execute(select(User).where(User.telegram_id == OWNER["telegram_id"]))
        if result.scalar_one_or_none():
            print("Demo data already seeded — skipping.")
            return

        # Owner
        owner = User(**OWNER)
        db.add(owner)
        await db.flush()

        # Owner settings
        settings = OwnerSettings(
            owner_id               = owner.id,
            daily_report_enabled   = True,
            daily_report_time      = "18:00",
            issue_notification_enabled = True,
            morning_nudge_enabled  = True,
            morning_nudge_time     = "07:30",
            checkin_interval_hours = 4,
        )
        db.add(settings)

        # Operators
        op_records = []
        for op_data in OPERATORS:
            op = User(**op_data, owner_id=owner.id)
            db.add(op)
            op_records.append(op)
        await db.flush()

        # Machines + MachineState + Assignments
        for i, m_data in enumerate(MACHINES):
            machine = Machine(**m_data, owner_id=owner.id)
            db.add(machine)
            await db.flush()

            state = MachineState(
                machine_id         = machine.id,
                status             = MachineStatus.IDLE.value,
                fuel_added_today   = 0.0,
                hours_worked_today = 0.0,
                open_issue_count   = 0,
            )
            db.add(state)

            # Assign one operator per machine
            assignment = MachineAssignment(
                machine_id  = machine.id,
                operator_id = op_records[i].id,
                is_active   = True,
            )
            db.add(assignment)

        await db.commit()

    print("Demo seed complete:")
    print(f"  Owner:      {OWNER['name']} (telegram_id={OWNER['telegram_id']})")
    for op in OPERATORS:
        print(f"  Operator:   {op['name']} (telegram_id={op['telegram_id']})")
    for m in MACHINES:
        print(f"  Machine:    {m['reg_number']} — {m['machine_type']} {m['model']}")


if __name__ == "__main__":
    asyncio.run(seed())
