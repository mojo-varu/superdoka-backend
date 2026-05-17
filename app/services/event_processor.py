"""
app/services/event_processor.py  — Hour 5

The pipeline orchestrator. Called by:
  - POST /vfm/update  (real-time path)
  - async_worker      (queue drain path)

Flow:
  1. Resolve operator DB record
  2. Run NER → get confidence → route
  3. If LLM route → call llm_fallback
  4. Resolve machine via SessionService
  5. Validate via Ontology (stub, upgraded in Phase 4)
  6. Write TimelineEvent + specific log table (atomic transaction)
  7. UPSERT MachineState
  8. Update session totals
  9. Evaluate rules → emit actions
  10. Return FleetUpdate with reply_text and actions populated
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context_llm  import context_extract, ExtractionResult, _call_llm
from app.core.text_normaliser import normalise_plate
from app.db.models import (
    FuelLog, GroupMessage, HoursLog, IssueReport,
    MachineState, MachineStatus, TimelineEvent, User,
    ProcessingStatus,
)
from app.schemas.fleet_update import (
    Action, ConfidenceRoute, FleetUpdate, Intent,
    MessageSource, Modality, SessionContext, Severity,
)
from app.services.session_service import session_service

logger = logging.getLogger(__name__)

# Reply templates (Russian)
REPLY_TEMPLATES = {
    "fuel_auto":        "Записал: {fuel_volume}л топлива ✓",
    "hours_auto":       "Записал: {hours}ч наработки ✓",
    "issue_auto":       "Зафиксировал: {description}. Приоритет: {priority}.",
    "shift_start":      "Смена открыта. Машина {reg_number} активна. Удачной смены!",
    "shift_end":        "Смена закончена. Сейчас рассчитаю итоги...",
    "needs_confirm":    "{summary}\n\nВсё верно? [Верно ✓] [Исправить ✗]",
    "needs_machine":    "Не могу определить машину. На какой технике работаете сегодня?",
    "clarification":    "Не распознал команду. Попробуйте ещё раз или начните смену: «Начинаю смену на [номер]»",
    "no_session":       "Вы не в смене. Напишите «Начинаю смену на [номер машины]»",
}


_CRITICAL_KEYWORDS = {"пожар", "горит", "огонь", "fire", "пожара", "горим"}

REAL_FIELDS = {
    "fuel_volume", "hours", "reg_number", "description",
    "production_qty", "production_unit", "notes",
}


class EventProcessor:
    """
    Stateless orchestrator — all state lives in DB / Redis.
    Create a new instance per request or reuse at module level.
    """

    def __init__(self):
        pass   # stateless — context_llm handles its own state

    # ── Main entry point ──────────────────────────────────────────────────

    async def process(
        self,
        db:     AsyncSession,
        update: FleetUpdate,
    ) -> FleetUpdate:
        """
        Run the full pipeline on a FleetUpdate.
        Mutates `update` in place and returns it.
        All DB writes are in a single transaction.
        """
        try:
            # Step 1 — resolve operator DB record
            await self._resolve_operator(db, update)

            # Step 2 — Intelligence: context-gated LLM extraction
            await self._run_intelligence(db, update, None)

            # Step 3 — Agency: session + machine resolution
            await self._resolve_session(db, update)

            # Step 4 — handle special intents before writing
            if update.intent == Intent.SHIFT_START:
                return await self._handle_shift_start(db, update)
            if update.intent == Intent.SHIFT_END:
                return await self._handle_shift_end(db, update)

            # Step 5 — require machine context for all logging intents
            if not update.has_active_session:
                update.reply_text = REPLY_TEMPLATES["no_session"]
                return update

            # Step 6 — write events to DB (atomic)
            await self._write_events(db, update)

            # Step 7 — evaluate rules
            await self._evaluate_rules(db, update)

            # Step 8 — agency reply for off-topic, else standard reply builder
            intent_val = getattr(update.intent, 'value', update.intent)
            if intent_val in ('unknown', 'clarification_needed'):
                real_missing = any(f in REAL_FIELDS for f in (getattr(update, '_missing_fields', None) or []))
                if not real_missing:
                    update.reply_text = await self._agency_reply(update, getattr(update, '_session_ctx', None))
                # else: reply_text already set by clarification handler in step 2
            else:
                self._build_reply(update)

            update.mark_processed()
            return update

        except Exception as e:
            logger.exception(f"EventProcessor.process failed: {e}")
            update.add_error(str(e))
            update.reply_text = REPLY_TEMPLATES["clarification"]
            return update

    # ── Step 1: Operator resolution ───────────────────────────────────────

    async def _resolve_operator(self, db: AsyncSession, update: FleetUpdate) -> None:
        if update.operator_db_id:
            return   # already resolved by ingest boundary
        result = await db.execute(
            select(User).where(
                User.platform_user_id == int(update.operator_id),
                User.is_active   == True,
            )
        )
        user = result.scalar_one_or_none()
        if user:
            update.operator_db_id = user.id
        else:
            update.add_error(f"Unknown operator platform_user_id={update.operator_id}")

    # ── Step 2: Intelligence (four-stage pipeline) ────────────────────────

    async def _run_intelligence(
        self, db: AsyncSession, update: FleetUpdate, session
    ) -> None:
        from app.core.intelligence_router import run_intelligence

        recent_history = await self._fetch_recent_history(db, update) \
                         if hasattr(self, '_fetch_recent_history') else None

        result = await run_intelligence(update, session, recent_history, db=db)

        update.intent           = result.intent
        update.entities         = result.entities or {}
        update.confidence       = result.confidence
        update.confidence_route = result.confidence_route
        object.__setattr__(update, '_missing_fields', result.missing_fields)
        object.__setattr__(update, '_session_ctx', session)

        REAL_FIELDS = {
            "fuel_volume", "hours", "reg_number", "description",
            "production_qty", "production_unit", "notes"
        }
        if result.clarification:
            missing = result.missing_fields or []
            if not missing:
                update.reply_text = result.clarification
            elif any(f in REAL_FIELDS for f in missing):
                update.reply_text = result.clarification

        for e in result.errors:
            update.add_error(e)

    # ── Step 3: Session & machine resolution ──────────────────────────────

    async def _resolve_session(self, db: AsyncSession, update: FleetUpdate) -> None:
        if not update.operator_db_id:
            return

        machine_id, reason = await session_service.resolve_machine_for_message(
            db          = db,
            operator_id = update.operator_db_id,
            reg_number  = update.reg_number,
        )

        if machine_id is None:
            return   # session not found — caller handles

        # Fetch MachineState for context
        state_result = await db.execute(
            select(MachineState).where(MachineState.machine_id == machine_id)
        )
        state = state_result.scalar_one_or_none()

        # Fetch active session for shift totals
        session = await session_service.get_active_session(db, update.operator_db_id)

        update.session = SessionContext(
            machine_id          = machine_id,
            open_issue_count    = state.open_issue_count if state else 0,
            fuel_logged_today   = state.fuel_added_today if state else 0.0,
            hours_logged_today  = state.hours_worked_today if state else 0.0,
            shift_started_at    = session.started_at if session else None,
            minutes_on_shift    = (
                int((datetime.utcnow() - session.started_at).total_seconds() / 60)
                if session else None
            ),
        )

    # ── Step 4a: Shift start ──────────────────────────────────────────────

    async def _handle_shift_start(
        self, db: AsyncSession, update: FleetUpdate
    ) -> FleetUpdate:
        reg = update.reg_number or update.entities.get("reg_number")
        if not reg:
            update.reply_text = "На какой машине начинаете смену? Укажите номер."
            return update

        machine = await session_service._resolve_machine_by_name(db, reg)
        if not machine:
            update.reply_text = f"Машина «{reg}» не найдена. Проверьте номер или позывной."
            return update

        await session_service.start_shift(
            db          = db,
            operator_id = update.operator_db_id,
            machine_id  = machine.id,
        )

        # Write timeline event
        event = TimelineEvent(
            machine_id  = machine.id,
            operator_id = update.operator_db_id,
            event_type  = "SHIFT_START",
            content     = {"reg_number": reg},
            raw_text    = update.raw_text,
            source      = update.source,
            confidence  = update.confidence,
            via_llm     = update.via_llm,
        )
        db.add(event)
        await db.commit()

        display_name = machine.alias or machine.reg_number
        update.reply_text = REPLY_TEMPLATES["shift_start"].format(reg_number=display_name)
        update.mark_processed()
        return update

    # ── Step 4b: Shift end ────────────────────────────────────────────────

    async def _handle_shift_end(
        self, db: AsyncSession, update: FleetUpdate
    ) -> FleetUpdate:
        session = await session_service.end_shift(db, update.operator_db_id)

        if session:
            event = TimelineEvent(
                machine_id  = session.machine_id,
                operator_id = update.operator_db_id,
                event_type  = "SHIFT_END",
                content     = {
                    "fuel_logged":  session.fuel_logged_this_shift,
                    "hours_logged": session.hours_logged_this_shift,
                    "checkin_count":session.checkin_count,
                },
                raw_text    = update.raw_text,
                source      = update.source,
                confidence  = update.confidence,
            )
            db.add(event)
            await db.commit()

        update.reply_text = REPLY_TEMPLATES["shift_end"]
        update.mark_processed()
        return update

    # ── Step 6: Write events ──────────────────────────────────────────────

    async def _write_events(self, db: AsyncSession, update: FleetUpdate) -> None:
        """
        Atomic write: TimelineEvent + specific log table + MachineState UPSERT.
        On CONFIRM route, writes with a provisional flag and sets
        needs_confirmation=True so ActionPlanner adds inline keyboard.
        """
        machine_id  = update.machine_id
        operator_id = update.operator_db_id

        # 1. TimelineEvent (always)
        event = TimelineEvent(
            machine_id  = machine_id,
            operator_id = operator_id,
            event_type  = self._intent_to_event_type(update.intent),
            content     = update.entities,
            raw_text    = update.raw_text,
            source      = update.source,
            confidence  = update.confidence,
            via_llm     = update.via_llm,
        )
        db.add(event)
        await db.flush()   # get event.id before inserting log rows
        update.timeline_event_id = event.id

        # 2. Specific log table
        if update.intent == Intent.FUEL_LOG:
            await self._write_fuel_log(db, update, event.id)
        elif update.intent == Intent.HOURS_LOG:
            await self._write_hours_log(db, update, event.id)
        elif update.intent == Intent.ISSUE_REPORT:
            await self._write_issue_report(db, update, event.id)

        # 3. MachineState UPSERT
        await self._upsert_machine_state(db, update)

        # 4. Session totals
        fuel_delta  = float(update.entities.get("fuel_volume", 0) or 0)
        hours_delta = float(update.entities.get("hours", 0) or 0)
        await session_service.update_session_totals(
            db          = db,
            operator_id = operator_id,
            fuel_delta  = fuel_delta,
            hours_delta = hours_delta,
        )

        await db.commit()

        # CONFIRM route → flag for inline keyboard
        if update.confidence_route == ConfidenceRoute.CONFIRM:
            update.needs_confirmation = True

    async def _write_fuel_log(
        self, db: AsyncSession, update: FleetUpdate, event_id: int
    ) -> None:
        vol = float(update.entities.get("fuel_volume") or 0)
        if vol <= 0:
            return
        log = FuelLog(
            machine_id        = update.machine_id,
            operator_id       = update.operator_db_id,
            fuel_volume       = vol,
            unit              = update.entities.get("unit", "литров"),
            original_text     = update.raw_text,
            parsed_data       = str(update.entities),
            timeline_event_id = event_id,
        )
        db.add(log)

    async def _write_hours_log(
        self, db: AsyncSession, update: FleetUpdate, event_id: int
    ) -> None:
        hrs = float(update.entities.get("hours") or 0)
        if hrs <= 0:
            return
        log = HoursLog(
            machine_id        = update.machine_id,
            operator_id       = update.operator_db_id,
            hours             = hrs,
            unit              = update.entities.get("unit", "часов"),
            original_text     = update.raw_text,
            parsed_data       = str(update.entities),
            timeline_event_id = event_id,
        )
        db.add(log)

    async def _write_issue_report(
        self, db: AsyncSession, update: FleetUpdate, event_id: int
    ) -> None:
        desc = (
            update.entities.get("description")
            or update.entities.get("notes")
            or update.raw_text[:200]
        )
        priority = self._severity_to_priority(update.severity)
        report = IssueReport(
            machine_id        = update.machine_id,
            operator_id       = update.operator_db_id,
            description       = desc,
            status            = "REPORTED",
            priority          = priority,
            original_text     = update.raw_text,
            parsed_data       = str(update.entities),
            timeline_event_id = event_id,
        )
        db.add(report)

        # Increment open issue count on MachineState
        state_result = await db.execute(
            select(MachineState).where(MachineState.machine_id == update.machine_id)
        )
        state = state_result.scalar_one_or_none()
        if state:
            state.open_issue_count += 1
            if priority in ("HIGH", "CRITICAL"):
                state.status = MachineStatus.WARNING.value

    async def _upsert_machine_state(
        self, db: AsyncSession, update: FleetUpdate
    ) -> None:
        result = await db.execute(
            select(MachineState).where(MachineState.machine_id == update.machine_id)
        )
        state = result.scalar_one_or_none()
        if state is None:
            state = MachineState(machine_id=update.machine_id)
            db.add(state)

        if update.intent == Intent.FUEL_LOG:
            vol = float(update.entities.get("fuel_volume") or 0)
            state.fuel_added_today      = (state.fuel_added_today or 0) + vol
            state.last_known_fuel_liters = vol   # last refuel amount
        elif update.intent == Intent.HOURS_LOG:
            hrs = float(update.entities.get("hours") or 0)
            state.hours_worked_today   = (state.hours_worked_today or 0) + hrs
            state.last_known_hours     = hrs

        state.last_event_at = datetime.utcnow()

    # ── Step 7: Rule evaluation ───────────────────────────────────────────

    async def _evaluate_rules(self, db: AsyncSession, update: FleetUpdate) -> None:
        """Delegated to RuleEngine — imported here to avoid circular imports."""
        from app.services.rule_engine import rule_engine
        actions = await rule_engine.evaluate(db, update)
        update.actions.extend(actions)
        update.rules_fired = rule_engine.last_fired_rule_ids

    # ── Agency reply for off-topic messages ──────────────────────────────

    async def _agency_reply(
        self, update: FleetUpdate, session: Optional[SessionContext]
    ) -> str:
        """
        Compact LLM call for messages that don't map to a fleet intent.
        Reacts naturally to what the operator said, then bridges back to the machine.
        """
        import json

        machine  = (session.machine_alias or session.machine_reg_number) if session else "машина"
        fuel     = session.fuel_logged_today  if session else 0
        hours    = session.hours_logged_today if session else 0
        issues   = session.open_issue_count   if session else 0

        context_line = f"Машина: {machine}. Топливо: {fuel}л. Наработка: {hours}ч."
        if issues:
            context_line += f" Открытых проблем: {issues}."

        system = (
            "Ты — VFM, помощник оператора строительной техники. "
            "Оператор написал что-то не связанное с работой машины. "
            "Ответь коротко (1-2 предложения): "
            "сначала отреагируй на сообщение по-человечески, "
            "затем мягко направь разговор к состоянию машины. "
            "Не используй шаблонные фразы. Будь живым."
            f"\nКонтекст смены: {context_line}"
        )

        try:
            raw = (await _call_llm(system, update.raw_text)).strip()
            if raw.startswith('{'):
                d = json.loads(raw)
                return d.get('reply', d.get('text', raw))
            return raw
        except Exception:
            return "Понял! Если что по машине — пиши."

    # ── Step 8: Build reply ───────────────────────────────────────────────

    def _build_reply(self, update: FleetUpdate) -> None:
        """Assemble the reply_text from intent + confidence route."""
        if update.reply_text:
            return   # already set by a special handler

        if update.intent == Intent.FUEL_LOG:
            base = REPLY_TEMPLATES["fuel_auto"].format(
                fuel_volume=update.entities.get("fuel_volume", "?")
            )
            if not re.search(r'\d+', update.raw_text):
                base += " — из контекста, верно?"
        elif update.intent == Intent.HOURS_LOG:
            base = REPLY_TEMPLATES["hours_auto"].format(
                hours=update.entities.get("hours", "?")
            )
        elif update.intent == Intent.ISSUE_REPORT:
            base = REPLY_TEMPLATES["issue_auto"].format(
                description=update.entities.get("description", update.raw_text[:50]),
                priority=self._severity_to_priority(update.severity),
            )
        elif update.intent == Intent.STATUS_UPDATE or getattr(update.intent, 'value', update.intent) == 'status_update':
            notes = update.entities.get("notes", "") or ""
            if notes and len(notes) >= 3:
                update.reply_text = f"Принято: {notes} ✓"
            else:
                update.reply_text = "Понял! Если что по машине — пиши."
            return
        elif not update.has_active_session:
            update.reply_text = REPLY_TEMPLATES["needs_machine"]
            return
        else:
            update.reply_text = REPLY_TEMPLATES["clarification"]
            return

        if update.needs_confirmation:
            update.reply_text = REPLY_TEMPLATES["needs_confirm"].format(summary=base)
        else:
            update.reply_text = base

    # ── Utilities ─────────────────────────────────────────────────────────

    @staticmethod
    def _intent_to_event_type(intent: Intent) -> str:
        mapping = {
            Intent.SHIFT_START:      "SHIFT_START",
            Intent.SHIFT_END:        "SHIFT_END",
            Intent.FUEL_LOG:         "FUEL_LOG",
            Intent.HOURS_LOG:        "HOURS_LOG",
            Intent.ISSUE_REPORT:     "ISSUE_REPORT",
            Intent.STATUS_UPDATE:    "STATUS_UPDATE",
            Intent.PRODUCTION_LOG:   "PRODUCTION_LOG",
            Intent.INSPECTION_CHECK: "INSPECTION_CHECK",
            Intent.PARTS_REQUEST:    "PARTS_REQUEST",
            Intent.HANDOVER_NOTE:    "HANDOVER_NOTE",
        }
        return mapping.get(intent, "STATUS_UPDATE")

    @staticmethod
    def _severity_to_priority(severity: Optional[Severity]) -> str:
        mapping = {
            Severity.INFO:     "LOW",
            Severity.WARNING:  "MEDIUM",
            Severity.HIGH:     "HIGH",
            Severity.CRITICAL: "CRITICAL",
        }
        return mapping.get(severity, "MEDIUM") if severity else "MEDIUM"


# Module-level singleton
event_processor = EventProcessor()
