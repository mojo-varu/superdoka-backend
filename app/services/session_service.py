"""
app/services/session_service.py  — Hour 4

The Agency pillar's foundation. Answers "Who is on what machine right now?"

Architecture:
  Redis  → primary read cache (sub-millisecond)
  Postgres active_sessions table → source of truth (survives restarts)

On startup: cache is warmed from Postgres.
On write:   Postgres first, then Redis (write-through).
If Redis is unavailable: graceful degradation to Postgres reads.

Binding lifecycle:
  IDLE   → no active session
  ACTIVE → operator bound to machine, all messages auto-routed
  ENDED  → shift closed, reconciliation triggered, row deleted
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Optional

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.text_normaliser import normalise_plate
from app.db.models import ActiveSession, Machine, MachineAssignment, MachineState, MachineStatus, ShiftState

logger = logging.getLogger(__name__)

# Redis key pattern: "session:{operator_db_id}"
_SESSION_KEY  = "session:{}"
_SESSION_TTL  = 60 * 60 * 14   # 14 hours — longer than any shift


# ---------------------------------------------------------------------------
# Redis client — optional, graceful fallback if not available
# ---------------------------------------------------------------------------
try:
    import redis.asyncio as aioredis
    _REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    _redis_client: Optional[aioredis.Redis] = aioredis.from_url(
        _REDIS_URL, encoding="utf-8", decode_responses=True
    )
except ImportError:
    logger.warning("redis package not installed — session cache disabled, using Postgres only")
    _redis_client = None


async def _redis_get(key: str) -> Optional[str]:
    if _redis_client is None:
        return None
    try:
        return await _redis_client.get(key)
    except Exception as e:
        logger.warning(f"Redis GET failed ({key}): {e}")
        return None


async def _redis_set(key: str, value: str, ttl: int = _SESSION_TTL) -> None:
    if _redis_client is None:
        return
    try:
        await _redis_client.set(key, value, ex=ttl)
    except Exception as e:
        logger.warning(f"Redis SET failed ({key}): {e}")


async def _redis_delete(key: str) -> None:
    if _redis_client is None:
        return
    try:
        await _redis_client.delete(key)
    except Exception as e:
        logger.warning(f"Redis DEL failed ({key}): {e}")


# ---------------------------------------------------------------------------
# SessionService
# ---------------------------------------------------------------------------

class SessionService:
    """
    All session operations go through this class.
    Inject via FastAPI Depends or instantiate directly in services.
    """

    # ── Read ──────────────────────────────────────────────────────────────

    async def get_active_session(
        self,
        db:          AsyncSession,
        operator_id: int,
    ) -> Optional[ActiveSession]:
        """
        Returns the operator's active session or None.
        Checks Redis first, falls back to Postgres.
        """
        # 1. Redis cache
        cache_key = _SESSION_KEY.format(operator_id)
        cached    = await _redis_get(cache_key)
        if cached:
            data = json.loads(cached)
            # Re-hydrate a lightweight object for callers that only need IDs
            session        = ActiveSession.__new__(ActiveSession)
            session.operator_id             = data["operator_id"]
            session.machine_id              = data["machine_id"]
            session.shift_state             = data["shift_state"]
            session.started_at              = datetime.fromisoformat(data["started_at"])
            session.fuel_logged_this_shift  = data.get("fuel_logged_this_shift", 0.0)
            session.hours_logged_this_shift = data.get("hours_logged_this_shift", 0.0)
            session.checkin_count           = data.get("checkin_count", 0)
            logger.debug(f"Session cache hit for operator {operator_id}")
            return session

        # 2. Postgres fallback
        result = await db.execute(
            select(ActiveSession).where(
                ActiveSession.operator_id == operator_id,
                ActiveSession.shift_state == ShiftState.ACTIVE.value,
            )
        )
        session = result.scalar_one_or_none()
        if session:
            await self._cache_session(session)
        return session

    async def get_machine_id_for_operator(
        self,
        db:          AsyncSession,
        operator_id: int,
    ) -> Optional[int]:
        """Lightweight helper — returns just the machine_id or None."""
        session = await self.get_active_session(db, operator_id)
        return session.machine_id if session else None

    # ── Write ─────────────────────────────────────────────────────────────

    async def start_shift(
        self,
        db:          AsyncSession,
        operator_id: int,
        machine_id:  int,
        expected_end: Optional[datetime] = None,
    ) -> ActiveSession:
        """
        Bind operator to machine for a shift.
        Creates/replaces ActiveSession row and warms Redis.
        Also transitions MachineState to WORKING.
        """
        # Close any existing session first (defensive)
        await self._close_session_row(db, operator_id)

        session = ActiveSession(
            operator_id  = operator_id,
            machine_id   = machine_id,
            shift_state  = ShiftState.ACTIVE.value,
            started_at   = datetime.utcnow(),
            last_seen_at = datetime.utcnow(),
            expected_end = expected_end,
        )
        db.add(session)

        # Update MachineState
        await self._upsert_machine_state(db, machine_id, operator_id, MachineStatus.WORKING)

        await db.commit()
        await db.refresh(session)
        await self._cache_session(session)

        logger.info(f"Shift started: operator={operator_id} machine={machine_id}")
        return session

    async def end_shift(
        self,
        db:          AsyncSession,
        operator_id: int,
    ) -> Optional[ActiveSession]:
        """
        Close the operator's active session.
        Transitions MachineState to IDLE.
        Returns the closed session for reconciliation.
        """
        session = await self.get_active_session(db, operator_id)
        if not session:
            logger.warning(f"end_shift called but no active session for operator {operator_id}")
            return None

        machine_id = session.machine_id

        # Mark ended in Postgres
        session.shift_state = ShiftState.ENDED.value
        await db.execute(
            delete(ActiveSession).where(ActiveSession.operator_id == operator_id)
        )

        # Update MachineState
        await self._upsert_machine_state(db, machine_id, None, MachineStatus.IDLE)

        await db.commit()
        await _redis_delete(_SESSION_KEY.format(operator_id))

        logger.info(f"Shift ended: operator={operator_id} machine={machine_id}")
        return session

    async def update_session_totals(
        self,
        db:              AsyncSession,
        operator_id:     int,
        fuel_delta:      float = 0.0,
        hours_delta:     float = 0.0,
        bump_checkin:    bool  = True,
    ) -> None:
        """
        Increment running totals after an event is written.
        Also updates last_seen_at (heartbeat).
        """
        result = await db.execute(
            select(ActiveSession).where(
                ActiveSession.operator_id == operator_id,
                ActiveSession.shift_state == ShiftState.ACTIVE.value,
            )
        )
        session = result.scalar_one_or_none()
        if not session:
            return

        session.fuel_logged_this_shift  += fuel_delta
        session.hours_logged_this_shift += hours_delta
        if bump_checkin:
            session.checkin_count += 1
        session.last_seen_at = datetime.utcnow()

        await db.commit()
        await self._cache_session(session)

    # ── Helpers ───────────────────────────────────────────────────────────

    async def _cache_session(self, session: ActiveSession) -> None:
        data = {
            "operator_id":             session.operator_id,
            "machine_id":              session.machine_id,
            "shift_state":             session.shift_state,
            "started_at":              session.started_at.isoformat(),
            "fuel_logged_this_shift":  session.fuel_logged_this_shift,
            "hours_logged_this_shift": session.hours_logged_this_shift,
            "checkin_count":           session.checkin_count,
        }
        await _redis_set(_SESSION_KEY.format(session.operator_id), json.dumps(data))

    async def _close_session_row(self, db: AsyncSession, operator_id: int) -> None:
        await db.execute(
            delete(ActiveSession).where(ActiveSession.operator_id == operator_id)
        )
        await _redis_delete(_SESSION_KEY.format(operator_id))

    async def _upsert_machine_state(
        self,
        db:          AsyncSession,
        machine_id:  int,
        operator_id: Optional[int],
        status:      MachineStatus,
    ) -> None:
        result = await db.execute(
            select(MachineState).where(MachineState.machine_id == machine_id)
        )
        state = result.scalar_one_or_none()
        if state is None:
            state = MachineState(machine_id=machine_id)
            db.add(state)

        state.status             = status.value
        state.active_operator_id = operator_id
        state.last_event_at      = datetime.utcnow()
        if status == MachineStatus.WORKING:
            state.shift_started_at = datetime.utcnow()

    async def get_assigned_machines(
        self, db: AsyncSession, operator_id: int
    ) -> list:
        """Return active Machine records assigned to this operator."""
        result = await db.execute(
            select(Machine)
            .join(MachineAssignment, MachineAssignment.machine_id == Machine.id)
            .where(
                MachineAssignment.operator_id == operator_id,
                MachineAssignment.is_active   == True,
                Machine.is_active             == True,
            )
        )
        return result.scalars().all()

    async def resolve_machine_for_message(
        self,
        db:          AsyncSession,
        operator_id: int,
        reg_number:  Optional[str] = None,
    ) -> tuple[Optional[int], str]:
        """
        Core routing logic used by EventProcessor.

        Returns (machine_id, routing_reason):
          - machine_id: int if resolved, None if unresolved
          - routing_reason: string explaining how it was resolved
            "session"              — from active session (zero-friction path)
            "name"                 — operator supplied reg/alias in message
            "single_assignment"    — operator has exactly one assigned machine
            "ambiguous_multi_machine" — multiple assignments, no reg supplied
            "none"                 — no assignments at all
        """
        # Priority 1: active session (zero-friction)
        machine_id = await self.get_machine_id_for_operator(db, operator_id)
        if machine_id:
            return machine_id, "session"

        # Priority 2-4: name supplied by NER (reg_number exact → alias exact → alias fuzzy)
        if reg_number:
            machine = await self._resolve_machine_by_name(db, reg_number)
            if machine:
                return machine.id, "name"

        # Priority 3: assigned machines — resolve silently if one, ask if many
        assigned = await self.get_assigned_machines(db, operator_id)
        if len(assigned) == 1:
            return assigned[0].id, "single_assignment"
        if len(assigned) > 1:
            return None, "ambiguous_multi_machine"

        # Cannot resolve
        return None, "none"

    async def _resolve_machine_by_name(
        self, db: AsyncSession, name: str
    ) -> Optional[Machine]:
        """
        Three-step lookup used whenever an operator mentions a machine by name:
          1. Exact match on reg_number   (А771МР77)
          2. Exact match on alias        (case-insensitive)
          3. Substring match on alias    (case-insensitive) — "комацу" hits "Комацу-7"
        Returns the first Machine found, or None.
        """
        name = normalise_plate(name)
        # Step 1: exact reg_number
        result = await db.execute(
            select(Machine).where(
                Machine.reg_number == name,
                Machine.is_active  == True,
            )
        )
        machine = result.scalar_one_or_none()
        if machine:
            return machine

        # Steps 2 & 3: fetch all active machines and compare alias in Python
        # (operator fleets are small; avoids DB-dialect ILIKE differences)
        all_result = await db.execute(
            select(Machine).where(
                Machine.is_active == True,
                Machine.alias     != None,
            )
        )
        candidates = all_result.scalars().all()

        name_lower = name.lower()

        # Step 2: exact alias match (case-insensitive)
        for m in candidates:
            if m.alias and m.alias.lower() == name_lower:
                return m

        # Step 3: alias contains the supplied name as a substring
        for m in candidates:
            if m.alias and name_lower in m.alias.lower():
                return m

        return None


# Module-level singleton
session_service = SessionService()
