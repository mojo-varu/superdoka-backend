"""
app/core/context_prompt.py

Compressed prompt builder for the VFM Intelligence layer.
Target: system prompt under 400 tokens on every call.

What was cut and why:
  - Intent descriptions removed — the model knows what fuel_log means
  - JSON schema comments removed — structure is self-evident
  - Examples reduced from 4 to 2 — one positive, one negative
  - History capped at 5 events (was 8)
  - Section headers shortened

What was kept:
  - Full session context injection (this is the core value)
  - Closed-world constraints (prevents the "which machine?" loop)
  - Complete JSON schema structure (field names unchanged)
  - One positive and one negative example
  - ЗАПРЕЩЕНО block (hallucination guardrails)
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from app.schemas.fleet_update import FleetUpdate, Intent, SessionContext


# ---------------------------------------------------------------------------
# Intent catalogue
# ---------------------------------------------------------------------------

INTENT_CATALOGUE: dict[str, str] = {
    "fuel_log":             "заправка топливом",
    "hours_log":            "наработка / моточасы",
    "issue_report":         "неисправность или проблема",
    "shift_start":          "начало смены",
    "shift_end":            "конец смены",
    "status_update":        "общий статус",
    "production_log":       "выработка (кубы, рейсы, тонны)",
    "inspection_check":     "осмотр / проверка",
    "parts_request":        "запрос запчастей",
    "handover_note":        "передача смены",
    "machine_switch":       "переход на другую машину",
    "clarification_needed": "непонятно, нужно уточнение",
}

REQUIRED_ENTITIES: dict[str, list[str]] = {
    "fuel_log":       ["fuel_volume"],
    "hours_log":      ["hours"],
    "issue_report":   [],  # description falls back to raw_text if absent
    "shift_start":    [],
    "shift_end":      [],
    "production_log": ["production_qty", "production_unit"],
    "parts_request":  ["description"],
    "handover_note":  ["notes"],
    "machine_switch": ["reg_number"],
}

NUMERIC_FIELDS = {"fuel_volume", "hours", "production_qty"}


# ---------------------------------------------------------------------------
# Compact JSON schema — single line, no comments
# ---------------------------------------------------------------------------

_SCHEMA = '{"intent":"<intent>","entities":{"fuel_volume":null,"hours":null,"reg_number":null,"description":null,"severity":"info|warning|high|critical","component":null,"symptom":null,"production_qty":null,"production_unit":null,"notes":null},"missing_fields":[],"confidence":0.95}'


# ---------------------------------------------------------------------------
# System prompt builder
# ---------------------------------------------------------------------------

def build_extraction_prompt(
    update:         FleetUpdate,
    session:        Optional[SessionContext],
    recent_history: list[dict[str, Any]] | None = None,
) -> tuple[str, str]:
    system = _build_system_prompt(session, recent_history)
    user   = update.raw_text.strip()
    return system, user


def _build_system_prompt(
    session:        Optional[SessionContext],
    recent_history: list[dict[str, Any]] | None,
) -> str:
    parts: list[str] = []

    # ── Role (2 lines) ────────────────────────────────────────────────────
    parts.append(
        "Извлекай структурированные данные из коротких сообщений операторов "
        "строительной техники. Сообщения разговорные, краткие, с опечатками."
    )

    # ── Session context ───────────────────────────────────────────────────
    parts.append(_format_session_context(session))

    # ── History (max 5 events, one line each) ─────────────────────────────
    if recent_history:
        parts.append(_format_history(recent_history))

    # ── Constraints ───────────────────────────────────────────────────────
    if session and session.machine_id:
        parts.append(
            "Машина и оператор известны из сессии. "
            "НЕ спрашивай номер машины. "
            "«Залил 50» без номера — нормально, машина привязана."
        )
    else:
        parts.append(
            "Активная смена не найдена. "
            "Для shift_start — извлеки reg_number из текста. "
            "Для остальных — верни clarification_needed."
        )

    # ── Intents (compact, one line) ───────────────────────────────────────
    intents_line = " | ".join(INTENT_CATALOGUE.keys())
    parts.append(f"Интенты: {intents_line}")

    # ── Schema ────────────────────────────────────────────────────────────
    parts.append(f"Ответ строго JSON: {_SCHEMA}")

    # ── Examples ──────────────────────────────────────────────────────────
    parts.append(
        'Пример топливо: «залил 50» при активной смене → '
        '{"intent":"fuel_log","entities":{"fuel_volume":50},"missing_fields":[],"confidence":0.97}'
    )
    parts.append(
        'мч/ч = моточасы. «8мч», «6ч», «наработ 5ч» → '
        '{"intent":"hours_log","entities":{"hours":8},"missing_fields":[],"confidence":0.95}'
    )
    parts.append(
        'Пример неясно: «50» без контекста → '
        '{"intent":"clarification_needed","entities":{},"missing_fields":["context"],"confidence":0.20}'
    )

    # ── Guardrails ────────────────────────────────────────────────────────
    from app.core.model_profiles import patch_forbidden_block
    parts.append(patch_forbidden_block())

    return "\n".join(parts)


def _format_session_context(session: Optional[SessionContext]) -> str:
    if session is None or session.machine_id is None:
        return "Смена: не открыта. Машина: неизвестна."

    parts = [f"Смена: активна. Машина: {session.machine_reg_number or '?'}"]

    if session.machine_type:
        parts[0] += f" ({session.machine_type})"

    if session.shift_started_at:
        mins = session.minutes_on_shift or 0
        h, m = divmod(mins, 60)
        parts.append(f"Длительность: {h}ч {m}м")

    stats = []
    if session.fuel_logged_today > 0:
        stats.append(f"топливо {session.fuel_logged_today:.0f}л")
    if session.hours_logged_today > 0:
        stats.append(f"наработка {session.hours_logged_today:.1f}ч")
    if session.open_issue_count > 0:
        stats.append(f"проблем {session.open_issue_count}")
    if stats:
        parts.append("Сегодня: " + ", ".join(stats))

    return " | ".join(parts)


def _format_history(history: list[dict[str, Any]]) -> str:
    """Last 5 events, one line each."""
    if not history:
        return ""

    lines = []
    for event in history[-5:]:
        ts      = event.get("created_at", "")
        etype   = event.get("event_type", "")
        content = event.get("content", {})
        raw     = event.get("raw_text", "")

        if isinstance(ts, datetime):
            ts_str = ts.strftime("%H:%M")
        elif ts:
            ts_str = str(ts)[:5]
        else:
            ts_str = "--:--"

        if etype == "FUEL_LOG" and "fuel_volume" in content:
            summary = f"+{content['fuel_volume']}л"
        elif etype == "HOURS_LOG" and "hours" in content:
            summary = f"+{content['hours']}ч"
        elif etype == "ISSUE_REPORT":
            summary = f"проблема: {content.get('description', raw)[:40]}"
        elif etype == "SHIFT_START":
            summary = "смена начата"
        elif etype == "SHIFT_END":
            summary = "смена закончена"
        else:
            summary = raw[:40] if raw else etype.lower()

        lines.append(f"{ts_str}:{summary}")

    return "История: " + " | ".join(lines)


# ---------------------------------------------------------------------------
# Clarification reply builder (unchanged — used by agency layer)
# ---------------------------------------------------------------------------

_CLARIFICATION_TEMPLATES: dict[str, str] = {
    "fuel_log:fuel_volume":      "Сколько литров?",
    "hours_log:hours":           "Сколько часов наработки?",
    "issue_report:description":  "Что именно случилось?",
    "shift_start:reg_number":    "На какой машине начинаете смену?",
    "production_log:production_qty": "Сколько {unit}?",
    "machine_switch:reg_number": "На какую машину переходите?",
    "parts_request:description": "Какая запчасть нужна?",
    "_default":                  "Уточните, пожалуйста.",
}


def build_clarification_reply(
    intent:         str,
    missing_fields: list[str],
    context:        Optional[SessionContext] = None,
) -> str:
    if not missing_fields:
        return ""
    for field in missing_fields:
        key = f"{intent}:{field}"
        if key in _CLARIFICATION_TEMPLATES:
            return _CLARIFICATION_TEMPLATES[key]
    return _CLARIFICATION_TEMPLATES["_default"]


# ---------------------------------------------------------------------------
# History summary prompt (used by Watcher for shift compaction)
# ---------------------------------------------------------------------------

def build_history_summary_prompt(
    history:     list[dict[str, Any]],
    machine_reg: str,
    max_chars:   int = 600,
) -> tuple[str, str]:
    system = (
        "Составь краткое резюме смены (2-3 предложения): "
        "наработка, топливо, проблемы, статус."
    )
    events_text = "\n".join(
        f"- {e.get('event_type','?')}: {json.dumps(e.get('content',{}), ensure_ascii=False)}"
        for e in history
    )
    user = f"Машина: {machine_reg}\n{events_text[:max_chars]}"
    return system, user


# ---------------------------------------------------------------------------
# Deterministic validators (no LLM required)
# ---------------------------------------------------------------------------

def detect_missing_fields(intent: str, entities: dict[str, Any]) -> list[str]:
    required = REQUIRED_ENTITIES.get(intent, [])
    return [
        f for f in required
        if entities.get(f) is None or entities.get(f) == ""
    ]


def validate_numeric_fields(entities: dict[str, Any]) -> list[str]:
    failures = []
    for field in NUMERIC_FIELDS:
        val = entities.get(field)
        if val is None:
            continue
        try:
            float(val)
        except (ValueError, TypeError):
            failures.append(field)
    return failures