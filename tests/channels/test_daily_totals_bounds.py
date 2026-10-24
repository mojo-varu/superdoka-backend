"""
tests/channels/test_daily_totals_bounds.py

AC-004-05 / test scenario 12 ("fuel_today is correct across a day boundary
in a non-UTC timezone") — the day-bounds math in app/services/daily_totals
is pure (no DB), so this is CONFIRMED-RUN. The actual SUM-query behaviour
against FuelLog/HoursLog (the rest of compute_today_totals) needs a real
database and is NOT executed in this sandbox — see the final report.
"""
from __future__ import annotations

from datetime import datetime

from app.services.daily_totals import _local_day_bounds_utc


def test_moscow_midnight_crossing():
    # Europe/Moscow is UTC+3 (no DST since 2014). 2026-10-24 23:30 Moscow
    # local time is 2026-10-24 20:30 UTC — still the SAME Moscow calendar
    # day as 2026-10-24 21:00 UTC (which is 2026-10-25 00:00 Moscow, the
    # START of the next local day). This is exactly the case the original
    # bug missed: a UTC-only day filter would put both in the same bucket.
    before_midnight_utc = datetime(2026, 10, 24, 20, 30)   # 23:30 Moscow — still Oct 24 locally
    after_midnight_utc = datetime(2026, 10, 24, 21, 30)    # 00:30 Moscow next day — Oct 25 locally

    start1, end1 = _local_day_bounds_utc("Europe/Moscow", before_midnight_utc)
    start2, end2 = _local_day_bounds_utc("Europe/Moscow", after_midnight_utc)

    assert start1 != start2, "two events either side of Moscow midnight must land in different local days"
    assert start1 <= before_midnight_utc < end1
    assert start2 <= after_midnight_utc < end2
    assert end1 == start2, "the end of one Moscow calendar day in UTC must equal the start of the next"


def test_utc_day_bounds_are_24_hours_apart():
    now = datetime(2026, 10, 24, 12, 0)
    start, end = _local_day_bounds_utc("UTC", now)
    assert (end - start).total_seconds() == 24 * 3600


if __name__ == "__main__":
    failures = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                failures += 1
                print(f"FAIL {name}: {e}")
    raise SystemExit(1 if failures else 0)
