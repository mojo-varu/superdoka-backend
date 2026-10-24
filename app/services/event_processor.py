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
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context_llm  import context_extract, ExtractionResult
from app.core.rephraser import rephrase_safe
from app.core.text_normaliser import normalise_plate

_PLATE_RE = re.compile(r'\b[А-ЯA-Zа-яa-z]\d{3}[А-ЯA-Zа-яa-z]{2}\d{2,3}\b')
from app.db.models import (
    FuelLog, GroupMessage, HoursLog, IssueReport,
    Machine, MachineState, MachineStatus, TimelineEvent, User,
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
    "fuel_auto":        "Принял, {fuel_volume} литров топлива записал.",
    "hours_auto":       "Принял, {hours} часов наработки записал.",
    "issue_auto":       "Проблема записана: {description}. Приоритет — {priority}.",
    "shift_start":      "Смена открыта. Машина {reg_number} активна. Удачной смены!",
    "shift_end":        "Смена закончена. Сейчас рассчитаю итоги...",
    "needs_confirm":    "{summary}\n\nВсё верно? [Верно ✓] [Исправить ✗]",
    "needs_machine":    "Не могу определить машину. На какой технике работаете сегодня?",
    "clarification":    "Не распознал команду. Попробуйте ещё раз или начните смену: «Начинаю смену на [номер]»",
    "no_session":       "Вы не в смене. Напишите «Начинаю смену на [номер машины]»",
}


_CRITICAL_KEYWORDS = {"пожар", "горит", "огонь", "fire", "пожара", "горим"}

# Only these intents produce a TimelineEvent row. All others are conversational.
OPERATIONAL_INTENTS = {"shift_start", "shift_end", "fuel_log", "hours_log", "issue_report"}

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
            object.__setattr__(update, '_reply_is_llm', False)

            # Step 1 — resolve operator DB record
            await self._resolve_operator(db, update)

            # Step 1b — fetch active session early so intelligence can gate correctly
            active_session = None
            if update.operator_db_id:
                active_session = await session_service.get_active_session(
                    db, update.operator_db_id
                )
            # Step 2 — Intelligence: context-gated LLM extraction
            await self._run_intelligence(db, update, active_session)

            # Step 3 — Agency: session + machine resolution
            await self._resolve_session(db, update)

            # Step 4 — handle special intents before writing
            if update.intent == Intent.SHIFT_START:
                return await self._handle_shift_start(db, update)
            if update.intent == Intent.SHIFT_END:
                return await self._handle_shift_end(db, update)

            # Step 5 — require machine context for all logging intents
            if not update.has_active_session:
                if not update.reply_text:
                    update.reply_text = REPLY_TEMPLATES["no_session"]
                return update

            # Step 6 — write events to DB (operational intents only)
            intent_val = getattr(update.intent, "value", update.intent)
            if intent_val in OPERATIONAL_INTENTS:
                await self._write_events(db, update)

            # Step 7 — evaluate rules
            await self._evaluate_rules(db, update)

            # Step 8 — off-topic reply via the single canonical T4 template
            # path, else standard reply builder. WP-G: this used to call
            # self._agency_reply() here, a third, independent, free-form LLM
            # call that overwrote whatever task_router/intelligence_router
            # had already decided for this message (see
            # task_router.build_offtopic_reply's docstring for the full
            # three-path history). Collapsed to one path, template-only,
            # matching ARCHITECTURE_VERBALIZED.md invariant 1 (T4 is always
            # deterministic).
            intent_val = getattr(update.intent, 'value', update.intent)
            if intent_val in ('unknown', 'clarification_needed'):
                real_missing = any(f in REAL_FIELDS for f in (getattr(update, '_missing_fields', None) or []))
                if not real_missing:
                    from app.core.task_router import build_offtopic_reply
                    context_graph = getattr(update, '_context_graph', None) or {}
                    session_ctx = getattr(update, '_session_ctx', None)
                    update.reply_text = build_offtopic_reply(context_graph, session_ctx)
                    object.__setattr__(update, '_reply_is_llm', False)
                # else: reply_text already set by clarification handler in step 2
            else:
                self._build_reply(update)

            # Rephrase happy-path replies. T8 exclusion handled inside rephrase_safe.
            # Error/rejection strings set via early returns bypass this block.
            if update.reply_text and not getattr(update, '_reply_is_llm', False):
                task_type = getattr(update, '_task_type', None)
                update.reply_text, rephrased = await rephrase_safe(
                    update.reply_text,
                    task_type=task_type,
                )
                object.__setattr__(update, '_rephrasing_rejected', not rephrased)

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
        object.__setattr__(update, '_task_type', result.task_type)

        REAL_FIELDS = {
            "fuel_volume", "hours", "reg_number", "description",
            "production_qty", "production_unit", "notes"
        }
        if result.clarification:
            missing = result.missing_fields or []
            _is_llm = result.task_type not in ("T1", "T2")
            if not missing:
                update.reply_text = result.clarification
                object.__setattr__(update, '_reply_is_llm', _is_llm)
            elif any(f in REAL_FIELDS for f in missing):
                update.reply_text = result.clarification
                object.__setattr__(update, '_reply_is_llm', _is_llm)

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
            if reason == "ambiguous_multi_machine":
                machines = await session_service.get_assigned_machines(
                    db, update.operator_db_id
                )
                regs = " или ".join(m.alias or m.reg_number for m in machines)
                update.reply_text = f"На какой машине работаешь? Уточни: {regs}"
            return

        # Fetch MachineState for context
        state_result = await db.execute(
            select(MachineState).where(MachineState.machine_id == machine_id)
        )
        state = state_result.scalar_one_or_none()

        # Fetch active session for shift totals
        session = await session_service.get_active_session(db, update.operator_db_id)

        # WP-G / SPEC-004-R10: computed from events in the org-local calendar
        # day, not the never-reset MachineState counters (see daily_totals.py).
        from app.services.daily_totals import compute_today_totals
        fuel_today, hours_today = await compute_today_totals(db, machine_id)

        update.session = SessionContext(
            machine_id          = machine_id,
            open_issue_count    = state.open_issue_count if state else 0,
            fuel_logged_today   = fuel_today,
            hours_logged_today  = hours_today,
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
        # Fix 2 — block if shift already active
        existing_machine_id = await session_service.get_machine_id_for_operator(
            db, update.operator_db_id
        )
        if existing_machine_id:
            result = await db.execute(
                select(Machine).where(Machine.id == existing_machine_id)
            )
            existing_machine = result.scalar_one_or_none()
            machine_name = (
                (existing_machine.alias or existing_machine.reg_number)
                if existing_machine else str(existing_machine_id)
            )
            update.reply_text = (
                f"Смена уже открыта на {machine_name}. "
                f"Чтобы сменить машину — сначала заверши текущую смену."
            )
            return update

        reg = update.reg_number or update.entities.get("reg_number")
        if reg:
            reg = normalise_plate(reg)
            # LLM sometimes returns just the first letter of a plate (e.g. "B" for "В542КХ77").
            # If the value isn't plate-shaped, scan the raw message for a full plate token.
            # If the scan also fails, discard reg so the single-assignment path takes over —
            # a single character like "В" must never reach alias substring matching, where
            # "в" would falsely match inside "экскаватор" and return the wrong machine.
            if not _PLATE_RE.fullmatch(reg):
                plates = _PLATE_RE.findall(update.raw_text or "")
                reg = normalise_plate(plates[0]) if plates else None
        if not reg:
            assigned = await session_service.get_assigned_machines(
                db, update.operator_db_id
            )
            if len(assigned) == 1:
                reg = assigned[0].reg_number
            elif len(assigned) > 1:
                regs = " или ".join(m.alias or m.reg_number for m in assigned)
                update.reply_text = f"На какой машине начинаешь смену? Уточни: {regs}"
                return update
            else:
                update.reply_text = "На какой машине начинаете смену? Укажите номер."
                return update

        machine = await session_service._resolve_machine_by_name(db, reg)
        if not machine:
            update.reply_text = f"Машина «{reg}» не найдена. Проверьте номер или позывной."
            return update

        # Fix 1 — block shift on unassigned machine
        assigned = await session_service.get_assigned_machines(db, update.operator_db_id)
        assigned_ids = {m.id for m in assigned}
        if machine.id not in assigned_ids:
            regs = ", ".join(m.alias or m.reg_number for m in assigned) if assigned else "—"
            display = machine.alias or machine.reg_number
            update.reply_text = (
                f"«{display}» не ваша машина. "
                f"Ваши машины: {regs}. Начните смену на одной из них."
            )
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
        reply = REPLY_TEMPLATES["shift_start"].format(reg_number=display_name)
        update.reply_text, _ = await rephrase_safe(reply, task_type="T1")
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

        update.reply_text, _ = await rephrase_safe(REPLY_TEMPLATES["shift_end"], task_type="T1_END")
        update.mark_processed()
        return update

    # ── Step 6: Write events ──────────────────────────────────────────────

    async def _write_events(self, db: AsyncSession, update: FleetUpdate) -> None:
        """
        WP-E / ADR-0023: AUTO-route events commit immediately via
        _commit_event (unchanged behaviour). CONFIRM-route and implausible
        results are staged in `pending_confirmations` instead — no
        TimelineEvent exists until the operator taps ✅. This fixes the
        pre-bot deviation where _write_events committed a TimelineEvent
        unconditionally and only set needs_confirmation=True afterward
        (confirmed in MVP_ASSESSMENT_FOR_CLAUDE.md §4 / ADR-0023's Context).
        app/services/confirmation_service.promote_pending_confirmation is
        what the ✅ callback calls to actually commit, reusing _commit_event.
        """
        if update.confidence_route == ConfidenceRoute.CONFIRM:
            import os
            from app.db.models import PendingConfirmation
            # ADR-0020: the engine must never import app/channels. The
            # expiry window (OQ-015-2 / ADR-0023) is read directly from the
            # same env var name app/channels/settings.py uses, independently,
            # rather than importing that module. A caught, real violation
            # from tests/channels/test_import_boundary.py — see final report.
            expiry_hours = int(os.getenv("BOT_CALLBACK_EXPIRY_HOURS", "24"))

            pending = PendingConfirmation(
                operator_id=update.operator_db_id,
                machine_id=update.machine_id,
                event_type=self._intent_to_event_type(update.intent),
                payload=update.entities,
                raw_text=update.raw_text,
                proposed_at=datetime.utcnow(),
                expires_at=datetime.utcnow() + timedelta(hours=expiry_hours),
            )
            db.add(pending)
            await db.commit()
            await db.refresh(pending)
            object.__setattr__(update, "_pending_confirmation_id", pending.id)
            update.needs_confirmation = True
            return

        await self._commit_event(db, update)

    async def _commit_event(self, db: AsyncSession, update: FleetUpdate) -> None:
        """
        The actual atomic write: TimelineEvent + specific log table +
        MachineState UPSERT + session totals, in one transaction. Called
        directly for AUTO-route events, and by
        confirmation_service.promote_pending_confirmation for a confirmed
        pending item — one write path, two callers (ADR-0023).
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
            update.raw_text
            or update.entities.get("description")
            or update.entities.get("notes")
            or ""
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

        # WP-G / SPEC-004-R10: fuel_added_today and hours_worked_today used to
        # be incremented here with a plain += and nothing ever reset them
        # (confirmed bug — MVP_ASSESSMENT_FOR_CLAUDE.md §5 item 3). They are
        # no longer written here; "today" is computed on read from
        # FuelLog/HoursLog via app/services/daily_totals.compute_today_totals,
        # scoped to the org-local calendar day. The columns remain on
        # MachineState only for the demo sandbox's static seed data
        # (app/api/v1/endpoints/demo.py, explicitly not touched this phase).
        if update.intent == Intent.FUEL_LOG:
            vol = float(update.entities.get("fuel_volume") or 0)
            state.last_known_fuel_liters = vol   # last refuel amount
        elif update.intent == Intent.HOURS_LOG:
            hrs = float(update.entities.get("hours") or 0)
            state.last_known_hours     = hrs

        state.last_event_at = datetime.utcnow()

    # ── Step 7: Rule evaluation ───────────────────────────────────────────

    async def _evaluate_rules(self, db: AsyncSession, update: FleetUpdate) -> None:
        """Delegated to RuleEngine — imported here to avoid circular imports."""
        from app.services.rule_engine import rule_engine
        actions = await rule_engine.evaluate(db, update)
        update.actions.extend(actions)
        update.rules_fired = rule_engine.last_fired_rule_ids

    # WP-G: _agency_reply (a third, independent, free-form LLM call for
    # off-topic messages) removed — see task_router.build_offtopic_reply's
    # docstring. Off-topic replies now go through the one canonical
    # template-only path (Step 8 above).

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
