"""
app/services/daily_totals.py

SPEC-004-R10 / WP-G fix: "today" values MUST be computed within the
org-local calendar day, using the org timezone — not accumulated into a
counter that never resets.

Previously, MachineState.fuel_added_today / hours_worked_today were
incremented with a plain += on every event (event_processor.py) with no
reset mechanism anywhere, so they grew across calendar days forever
(confirmed in MVP_ASSESSMENT_FOR_CLAUDE.md §5 item 3; SHIPPABLE_SCOPE.md §2).
This module computes the same two numbers fresh, from FuelLog/HoursLog,
scoped to the org-local calendar day, so there is nothing to reset.

The MachineState columns themselves are left in place (removing them is a
larger migration touching the sandbox seed data, out of scope for this
pass — event_processor._upsert_machine_state no longer increments them, see
WP-G note there) but no code should read them for "today" semantics anymore;
callers should use this module instead. See docs/proposals/AMENDMENTS.md for
the full list of call sites updated vs. left as a follow-up.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
# sqlalchemy import deliberately deferred into the two functions that need
# it (below), not at module scope — this sandbox has no sqlalchemy
# installed, and deferring the import lets _local_day_bounds_utc (pure
# datetime math) be unit-tested on its own. See
# tests/channels/test_daily_totals_bounds.py and the final report.

try:
    from zoneinfo import ZoneInfo
except ImportError:   # pragma: no cover — Python < 3.9, not expected here
    ZoneInfo = None   # type: ignore

DEFAULT_TIMEZONE = "Europe/Moscow"


async def _org_timezone_for_machine(db: AsyncSession, machine_id: int) -> str:
    from sqlalchemy import select
    from app.db.models import Machine, Org
    result = await db.execute(
        select(Org.timezone)
        .join(Machine, Machine.org_id == Org.id)
        .where(Machine.id == machine_id)
    )
    tz = result.scalar_one_or_none()
    return tz or DEFAULT_TIMEZONE


def _local_day_bounds_utc(tz_name: str, now_utc: Optional[datetime] = None) -> tuple[datetime, datetime]:
    """
    Returns (start_of_local_day_in_utc, end_of_local_day_in_utc) as naive UTC
    datetimes, matching the naive datetime.utcnow() convention used
    throughout the rest of this codebase (SPEC-011-R12 wants timestamptz;
    the existing schema stores naive UTC — not changed in this pass).
    """
    now_utc = now_utc or datetime.utcnow()
    if ZoneInfo is None:
        # Fallback: treat as UTC if zoneinfo is unavailable.
        start_local = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        return start_local, start_local + timedelta(days=1)

    tz = ZoneInfo(tz_name)
    local_now = now_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz)
    start_local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local_midnight = start_local_midnight + timedelta(days=1)
    start_utc = start_local_midnight.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    end_utc = end_local_midnight.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    return start_utc, end_utc


async def compute_today_totals(
    db: AsyncSession,
    machine_id: int,
    now_utc: Optional[datetime] = None,
) -> tuple[float, float]:
    """
    Returns (fuel_today, hours_today) for machine_id, scoped to the
    org-local calendar day. AC-004-05: correct across a day boundary in a
    non-UTC timezone.
    """
    from sqlalchemy import func, select
    from app.db.models import FuelLog, HoursLog

    tz_name = await _org_timezone_for_machine(db, machine_id)
    start_utc, end_utc = _local_day_bounds_utc(tz_name, now_utc)

    fuel_result = await db.execute(
        select(func.coalesce(func.sum(FuelLog.fuel_volume), 0.0)).where(
            FuelLog.machine_id == machine_id,
            FuelLog.created_at >= start_utc,
            FuelLog.created_at < end_utc,
        )
    )
    hours_result = await db.execute(
        select(func.coalesce(func.sum(HoursLog.hours), 0.0)).where(
            HoursLog.machine_id == machine_id,
            HoursLog.created_at >= start_utc,
            HoursLog.created_at < end_utc,
        )
    )
    return float(fuel_result.scalar_one() or 0.0), float(hours_result.scalar_one() or 0.0)
