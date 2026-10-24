"""
app/services/metrics.py

WP-G / SPEC-010-R12: expose the operator correction rate as a query.
Minimal implementation — the full harness (replay CLI, golden set, version
stamps) is SPEC-010 and explicitly out of scope for this phase; this is just
the one metric WP-G asks for, so correction behaviour is visible without
hand-querying the database.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TimelineEvent


async def correction_rate(
    db: AsyncSession,
    operator_id: Optional[int] = None,
    since: Optional[datetime] = None,
) -> dict:
    """
    Returns {"confirmed_events": N, "corrections": M, "rate": M/N or 0.0}.
    "Confirmed events" excludes CORRECTION rows themselves (a correction is
    not itself a thing that can be corrected in this count — it would double
    count). Scoped to operator_id if given, else org-wide (single default
    org today — see docs/proposals/AMENDMENTS.md on tenancy).
    """
    since = since or (datetime.utcnow() - timedelta(days=30))

    base_filter = [TimelineEvent.created_at >= since]
    if operator_id is not None:
        base_filter.append(TimelineEvent.operator_id == operator_id)

    confirmed_result = await db.execute(
        select(func.count(TimelineEvent.id)).where(
            TimelineEvent.event_type != "CORRECTION", *base_filter
        )
    )
    corrections_result = await db.execute(
        select(func.count(TimelineEvent.id)).where(
            TimelineEvent.event_type == "CORRECTION", *base_filter
        )
    )
    confirmed = int(confirmed_result.scalar_one() or 0)
    corrections = int(corrections_result.scalar_one() or 0)

    return {
        "confirmed_events": confirmed,
        "corrections": corrections,
        "rate": round(corrections / confirmed, 4) if confirmed else 0.0,
        "since": since.isoformat(),
    }
