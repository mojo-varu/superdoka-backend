"""
app/core/context_graph.py
==========================
Builds the VFM context graph — a structured, living memory of each machine.

The graph has three temporal layers:
  1. Immediate  — current shift state (always fresh)
  2. Recent     — 7-30 day trends (cached on MachineState, refreshed by Watcher)
  3. Historical — lifetime totals (accumulates silently)

The graph feeds two consumers:
  - TaskRouter  — reads `signals` to decide T1-T8 routing
  - Agency LLM  — reads the full graph to reason contextually

Key design principle: the graph encodes what a supervisor KNOWS about
a machine, not just what happened in this session. VFM's judgment
improves as the graph gets richer over time.

Usage:
    graph = await build_context_graph(machine_id, operator_id, session, db)
    signals = graph["signals"]   # pre-computed flags for TaskRouter
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    FuelLog,
    HoursLog,
    IssueReport,
    Machine,
    MachineState,
    TimelineEvent,
    User,
)

logger = logging.getLogger(__name__)

# ── Signal thresholds ─────────────────────────────────────────────────────────
FUEL_ANOMALY_THRESHOLD    = 1.20   # 20% above rolling baseline
SILENCE_WARNING_MINUTES   = 90     # no message for 90 min during active shift
RECURRENCE_THRESHOLD      = 2      # same component N+ times in 30 days
SERVICE_WARNING_HOURS     = 50     # hours before service is due → warn
MIN_SHIFTS_FOR_BASELINE   = 5      # need at least N shifts to establish baseline


async def build_context_graph(
    machine_id:  int,
    operator_id: int,
    session_ctx: Any,          # SessionContext or None
    db:          AsyncSession,
) -> dict[str, Any]:
    """
    Build the full context graph for a machine+operator pair.
    Called once per incoming message before agency layer routing.
    Target latency: < 50ms (3-4 indexed queries).
    """
    graph: dict[str, Any] = {}

    try:
        # Fetch machine and operator in parallel conceptually (sequential here
        # but all queries use primary key or indexed columns)
        machine  = await _fetch_machine(machine_id, db)
        operator = await _fetch_operator(operator_id, db)
        state    = await _fetch_machine_state(machine_id, db)

        graph["machine"]          = _build_machine_layer(machine, state)
        graph["current_shift"]    = _build_shift_layer(session_ctx, state)
        graph["operator_profile"] = await _build_operator_profile(
                                        operator_id, machine_id, db)
        graph["recent_trend"]     = await _build_recent_trend(
                                        machine_id, db)
        graph["vfm_state"]        = _build_vfm_state(session_ctx)
        graph["signals"]          = _compute_signals(graph)

    except Exception as e:
        logger.error(f"Context graph build failed for machine {machine_id}: {e}")
        graph["signals"] = {}
        graph["error"]   = str(e)

    return graph


# ── Layer builders ────────────────────────────────────────────────────────────

def _build_machine_layer(machine: Optional[Machine],
                         state: Optional[MachineState]) -> dict:
    if not machine:
        return {}
    return {
        "machine_id":   machine.id,
        "reg_number":   machine.reg_number,
        "alias":        machine.alias or machine.reg_number,
        "type":         machine.machine_type,
        "model":        machine.model,
        "status":       state.status if state else "IDLE",
    }


def _build_shift_layer(session_ctx: Any,
                       state: Optional[MachineState]) -> dict:
    if not session_ctx or not getattr(session_ctx, "machine_id", None):
        return {"active": False}

    now       = datetime.utcnow()
    started   = getattr(session_ctx, "shift_started_at", None)
    duration  = int((now - started).total_seconds() / 60) if started else 0

    last_event_at = getattr(state, "last_event_at", None) if state else None
    silence_min   = int((now - last_event_at).total_seconds() / 60) \
                    if last_event_at else duration

    fuel_today  = getattr(session_ctx, "fuel_logged_today", 0) or 0
    hours_today = getattr(session_ctx, "hours_logged_today", 0) or 0
    fuel_rate   = round(fuel_today / hours_today, 1) if hours_today > 0 else 0.0

    return {
        "active":                True,
        "operator_name":         getattr(session_ctx, "operator_name", ""),
        "duration_minutes":      duration,
        "fuel_logged":           fuel_today,
        "hours_logged":          hours_today,
        "fuel_rate_today":       fuel_rate,
        "open_issues":           getattr(state, "open_issue_count", 0) if state else 0,
        "last_message_min_ago":  silence_min,
        "started_at":            started.strftime("%H:%M") if started else "",
    }


async def _build_operator_profile(
    operator_id: int,
    machine_id:  int,
    db:          AsyncSession,
) -> dict:
    """
    Derive operator communication style from recent TimelineEvent history.
    No stored profile — computed dynamically and improves with data.
    """
    result = await db.execute(
        select(TimelineEvent)
        .where(
            TimelineEvent.operator_id == operator_id,
            TimelineEvent.machine_id  == machine_id,
            TimelineEvent.created_at  >= datetime.utcnow() - timedelta(days=30),
        )
        .order_by(TimelineEvent.id.desc())
        .limit(50)
    )
    events = result.scalars().all()

    if not events:
        return {
            "name":               "",
            "style":              "unknown",
            "avg_message_length": 0,
            "shifts_on_machine":  0,
            "uses_abbreviations": False,
        }

    messages   = [e.raw_text or "" for e in events if e.raw_text]
    avg_len    = sum(len(m.split()) for m in messages) / len(messages) if messages else 0
    style      = "terse" if avg_len <= 4 else "verbose" if avg_len >= 10 else "normal"

    # Detect abbreviations — short unit forms indicate abbreviation use
    abbrev_patterns = ["мч", "лт", "ч ", "л ", "наработ", "залил"]
    uses_abbrev = any(
        any(p in m.lower() for p in abbrev_patterns)
        for m in messages
    )

    # Count distinct shifts as a proxy for operator familiarity
    shift_starts = sum(1 for e in events if e.event_type == "SHIFT_START")

    return {
        "style":              style,
        "avg_message_length": round(avg_len, 1),
        "shifts_on_machine":  shift_starts,
        "uses_abbreviations": uses_abbrev,
        "message_count_30d":  len(events),
    }


async def _build_recent_trend(
    machine_id: int,
    db:         AsyncSession,
) -> dict:
    """
    7-30 day operational trends. The heart of VFM's machine memory.
    """
    cutoff_30d = datetime.utcnow() - timedelta(days=30)
    cutoff_7d  = datetime.utcnow() - timedelta(days=7)

    # ── Fuel trend ────────────────────────────────────────────────────────────
    fuel_result = await db.execute(
        select(
            func.sum(FuelLog.fuel_volume).label("total"),
            func.count(FuelLog.id).label("count"),
            func.avg(FuelLog.fuel_volume).label("avg_per_log"),
        )
        .where(
            FuelLog.machine_id == machine_id,
            FuelLog.created_at >= cutoff_30d,
        )
    )
    fuel_row = fuel_result.one()

    fuel_7d_result = await db.execute(
        select(func.sum(FuelLog.fuel_volume))
        .where(
            FuelLog.machine_id == machine_id,
            FuelLog.created_at >= cutoff_7d,
        )
    )
    fuel_7d = float(fuel_7d_result.scalar() or 0)

    # ── Hours trend ───────────────────────────────────────────────────────────
    hours_result = await db.execute(
        select(
            func.sum(HoursLog.hours).label("total"),
            func.avg(HoursLog.hours).label("avg_per_shift"),
        )
        .where(
            HoursLog.machine_id == machine_id,
            HoursLog.created_at >= cutoff_30d,
        )
    )
    hours_row = hours_result.one()

    total_fuel_30d  = float(fuel_row.total  or 0)
    total_hours_30d = float(hours_row.total or 0)

    # Fuel rate baseline
    fuel_rate_baseline = round(total_fuel_30d / total_hours_30d, 1) \
                         if total_hours_30d > 0 else 0.0

    # ── Issue pattern ─────────────────────────────────────────────────────────
    issue_result = await db.execute(
        select(IssueReport.description, IssueReport.priority, IssueReport.created_at)
        .where(
            IssueReport.machine_id == machine_id,
            IssueReport.created_at >= cutoff_30d,
        )
        .order_by(IssueReport.created_at.desc())
    )
    issues = issue_result.all()

    # Extract component mentions from descriptions
    component_keywords = {
        "hydraulics":    ["гидравлик", "гидравл"],
        "engine":        ["двигател", "мотор", "engine"],
        "tracks":        ["ходов", "гусениц", "track"],
        "transmission":  ["трансмисс", "коробк"],
        "brakes":        ["тормоз"],
        "bucket":        ["ковш", "bucket"],
        "electrical":    ["электр", "аккумул", "генератор"],
    }

    component_counts: Counter = Counter()
    for issue in issues:
        desc = (issue.description or "").lower()
        for comp, keywords in component_keywords.items():
            if any(kw in desc for kw in keywords):
                component_counts[comp] += 1

    recurring_component = None
    recurring_count     = 0
    if component_counts:
        top_comp, top_count = component_counts.most_common(1)[0]
        if top_count >= RECURRENCE_THRESHOLD:
            recurring_component = top_comp
            recurring_count     = top_count

    # ── Assemble trend ────────────────────────────────────────────────────────
    return {
        "fuel_total_30d":       round(total_fuel_30d, 1),
        "fuel_total_7d":        round(fuel_7d, 1),
        "fuel_rate_baseline":   fuel_rate_baseline,
        "hours_total_30d":      round(total_hours_30d, 1),
        "issue_count_30d":      len(issues),
        "recurring_component":  recurring_component,
        "recurring_count":      recurring_count,
        "has_baseline":         total_hours_30d > 0,
    }


def _build_vfm_state(session_ctx: Any) -> dict:
    return {
        "pending_clarification":         getattr(session_ctx, "pending_clarification_field", None),
        "proactive_messages_unanswered": getattr(session_ctx, "proactive_unanswered", 0),
        "silence_until":                 None,
    }


# ── Signal computation ────────────────────────────────────────────────────────

def _compute_signals(graph: dict) -> dict:
    """
    Pre-compute boolean/string signals for TaskRouter.
    All threshold logic lives here — TaskRouter reads signals, not raw data.
    """
    signals: dict[str, Any] = {}

    shift   = graph.get("current_shift", {})
    trend   = graph.get("recent_trend",  {})

    # ── Fuel anomaly ──────────────────────────────────────────────────────────
    baseline = trend.get("fuel_rate_baseline", 0)
    current  = shift.get("fuel_rate_today", 0)
    if baseline > 0 and current > 0:
        delta_pct = (current - baseline) / baseline
        if delta_pct > (FUEL_ANOMALY_THRESHOLD - 1):
            signals["fuel_anomaly"] = (
                f"расход {current}л/ч против нормы {baseline}л/ч "
                f"(+{round(delta_pct * 100)}%)"
            )

    # ── Recurring issue ───────────────────────────────────────────────────────
    comp  = trend.get("recurring_component")
    count = trend.get("recurring_count", 0)
    if comp and count >= RECURRENCE_THRESHOLD:
        comp_ru = {
            "hydraulics":   "гидравлика",
            "engine":       "двигатель",
            "tracks":       "ходовая",
            "transmission": "трансмиссия",
            "brakes":       "тормоза",
            "electrical":   "электрика",
        }.get(comp, comp)
        signals["recurring_issue"] = f"{comp_ru} × {count} за 30 дней"

    # ── Machine silent during active shift ────────────────────────────────────
    if shift.get("active") and shift.get("last_message_min_ago", 0) > SILENCE_WARNING_MINUTES:
        signals["machine_silent"] = (
            f"нет сообщений {shift['last_message_min_ago']} мин"
        )

    # ── Open issues requiring attention ───────────────────────────────────────
    open_issues = shift.get("open_issues", 0)
    if open_issues > 0:
        signals["open_issues"] = open_issues

    # ── High issue volume ─────────────────────────────────────────────────────
    if trend.get("issue_count_30d", 0) > 5:
        signals["high_issue_volume"] = trend["issue_count_30d"]

    return signals


# ── DB helpers ────────────────────────────────────────────────────────────────

async def _fetch_machine(machine_id: int,
                         db: AsyncSession) -> Optional[Machine]:
    r = await db.execute(select(Machine).where(Machine.id == machine_id))
    return r.scalar_one_or_none()


async def _fetch_operator(operator_id: int,
                          db: AsyncSession) -> Optional[User]:
    r = await db.execute(select(User).where(User.id == operator_id))
    return r.scalar_one_or_none()


async def _fetch_machine_state(machine_id: int,
                               db: AsyncSession) -> Optional[MachineState]:
    r = await db.execute(
        select(MachineState).where(MachineState.machine_id == machine_id)
    )
    return r.scalar_one_or_none()


# ── Compact serialiser for agency prompt injection ────────────────────────────

def serialise_for_prompt(graph: dict) -> str:
    """
    Serialise context graph to labelled-section format.
    Identical format used in probes and training data.
    Target: under 150 tokens.
    """
    sections = []

    # [МАШИНА]
    m = graph.get("machine", {})
    if m:
        lines = ["[МАШИНА]"]
        if m.get("alias") or m.get("reg_number"):
            lines.append(f"Название: {m.get('alias', m.get('reg_number', '?'))}")
        if m.get("type"):
            lines.append(f"Тип: {m['type']}")
        sections.append("\n".join(lines))

    # [СМЕНА]
    s = graph.get("current_shift", {})
    if s.get("active"):
        lines = ["[СМЕНА]"]
        lines.append(f"Длительность: {s.get('duration_minutes', 0)} мин")
        if s.get("fuel_logged", 0) > 0:
            lines.append(f"Топливо: {s['fuel_logged']} л")
        if s.get("hours_logged", 0) > 0:
            lines.append(f"Наработка: {s['hours_logged']} ч")
        last = s.get("last_message_min_ago", 0)
        if last > 0:
            lines.append(f"Последнее сообщение: {last} мин назад")
        sections.append("\n".join(lines))

    # [ПРОБЛЕМЫ]
    signals     = graph.get("signals", {})
    open_issues = s.get("open_issues", 0) if s else 0
    recurring   = signals.get("recurring_issue", "")
    if open_issues > 0 or recurring:
        lines = ["[ПРОБЛЕМЫ]"]
        lines.append(f"Открытых: {open_issues}")
        if recurring:
            lines.append(f"- {recurring}")
        sections.append("\n".join(lines))

    # [СИГНАЛЫ]
    signal_lines = []
    if signals.get("fuel_anomaly"):
        signal_lines.append(f"- {signals['fuel_anomaly']}")
    if signals.get("machine_silent"):
        signal_lines.append(f"- {signals['machine_silent']}")
    if signal_lines:
        sections.append("[СИГНАЛЫ]\n" + "\n".join(signal_lines))

    return "\n\n".join(sections) if sections else "[КОНТЕКСТ]\nДанные накапливаются."
