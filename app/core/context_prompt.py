"""
app/core/context_prompt.py

Builds the context-gated LLM prompt for the VFM Intelligence layer.
Replaces the blind SYSTEM_PROMPT in llm_fallback.py with a prompt
that is pre-loaded with everything the SessionService already knows.

Three functions exposed:

  build_extraction_prompt(update, session)
      → returns (system_prompt, user_message) ready for any LLM API
        The session context narrows the LLM's extraction surface to
        2-3 fields rather than the full open-ended problem.

  build_clarification_prompt(update, session, missing_fields)
      → returns the Russian reply to ask the operator for missing data
        Templated so the bot sounds consistent, not robotic.

  build_conversation_summary_prompt(history)
      → returns a prompt that summarises recent machine conversation
        history for injecting as long-term context.

Design principles:
  1. Context first — session data is injected at the TOP of the system
     prompt, before any task description. This anchors the LLM.
  2. Closed-world constraint — the prompt explicitly tells the LLM that
     machine and operator are already known so it MUST NOT ask for them.
  3. JSON schema enforcement — the expected output schema is embedded
     directly, with field-level comments explaining what each field means
     in the fleet domain.
  4. Negative examples — the prompt includes examples of what NOT to do
     (hallucinate a reg number, invent a fuel volume) which measurably
     reduces hallucination on numeric fields.
  5. Conversation history — the last N timeline events for this machine
     are summarised and injected so the LLM has shift-level memory.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from app.schemas.fleet_update import FleetUpdate, Intent, SessionContext


# ---------------------------------------------------------------------------
# Intent catalogue — what the LLM can classify
# (deliberately minimal — we add more by editing this dict, not retraining)
# ---------------------------------------------------------------------------

INTENT_CATALOGUE: dict[str, str] = {
    "fuel_log":         "Оператор сообщает о заправке топливом",
    "hours_log":        "Оператор сообщает о наработке (моточасах)",
    "issue_report":     "Оператор сообщает о неисправности или проблеме",
    "shift_start":      "Оператор начинает смену",
    "shift_end":        "Оператор заканчивает смену",
    "status_update":    "Общий статус без конкретного события (всё нормально, ждём, стоим)",
    "production_log":   "Оператор сообщает о выработке (кубов, рейсов, тонн)",
    "inspection_check": "Оператор сообщает о результате осмотра или проверки",
    "parts_request":    "Оператор запрашивает запчасти или расходники",
    "handover_note":    "Оператор передаёт смену другому оператору",
    "machine_switch":   "Оператор переходит на другую машину",
    "clarification_needed": "Сообщение непонятно, требует уточнения",
}

# Required entities per intent — drives the missing-field detection
REQUIRED_ENTITIES: dict[str, list[str]] = {
    "fuel_log":         ["fuel_volume"],
    "hours_log":        ["hours"],
    "issue_report":     ["description"],
    "shift_start":      [],   # machine resolved from session or reg_number
    "shift_end":        [],
    "production_log":   ["production_qty", "production_unit"],
    "parts_request":    ["description"],
    "handover_note":    ["notes"],
    "machine_switch":   ["reg_number"],   # needs new machine
}

# Fields where the LLM must return a number (not a string)
NUMERIC_FIELDS = {"fuel_volume", "hours", "production_qty"}


# ---------------------------------------------------------------------------
# System prompt builder
# ---------------------------------------------------------------------------

def build_extraction_prompt(
    update:           FleetUpdate,
    session:          Optional[SessionContext],
    recent_history:   list[dict[str, Any]] | None = None,
) -> tuple[str, str]:
    """
    Build the (system_prompt, user_message) pair for the LLM API call.

    The system_prompt contains:
      - Current context (machine, operator, shift state)
      - Recent conversation history for this machine
      - Full extraction task with JSON schema
      - Negative examples (hallucination guardrails)

    The user_message is the sanitised operator text.

    Returns a tuple: (system_prompt, user_message)
    """
    system_prompt = _build_system_prompt(session, recent_history)
    user_message  = _build_user_message(update)
    return system_prompt, user_message


def _build_system_prompt(
    session:        Optional[SessionContext],
    recent_history: list[dict[str, Any]] | None,
) -> str:

    parts: list[str] = []

    # ── Section 1: Role definition ─────────────────────────────────────────
    parts.append(
        "Ты — система анализа сообщений операторов тяжёлой строительной техники.\n"
        "Твоя задача: извлечь структурированные данные из короткого сообщения оператора.\n"
        "Оператор пишет в мессенджер — сообщения короткие, разговорные, иногда с опечатками."
    )

    # ── Section 2: Current context (the key difference vs Option B) ────────
    parts.append("\n## ТЕКУЩИЙ КОНТЕКСТ")
    parts.append(_format_session_context(session))

    # ── Section 3: Conversation history for this machine ──────────────────
    if recent_history:
        parts.append("\n## ИСТОРИЯ СООБЩЕНИЙ ПО ЭТОЙ МАШИНЕ (последние события)")
        parts.append(_format_history(recent_history))

    # ── Section 4: Closed-world constraints ───────────────────────────────
    parts.append("\n## ВАЖНЫЕ ОГРАНИЧЕНИЯ")
    if session and session.machine_id:
        parts.append(
            "- Машина уже определена из сессии — НЕ спрашивай и не угадывай номер машины.\n"
            "- Оператор уже известен — НЕ спрашивай кто пишет.\n"
            "- Если оператор пишет «залил 50» без номера машины — это нормально, машина уже привязана."
        )
    else:
        parts.append(
            "- Активная смена НЕ найдена.\n"
            "- Если сообщение выглядит как начало смены (shift_start) — извлеки номер машины из текста.\n"
            "- Для других интентов — сообщи что требуется начать смену."
        )

    # ── Section 5: Intent catalogue ───────────────────────────────────────
    parts.append("\n## ВОЗМОЖНЫЕ ИНТЕНТЫ")
    for intent, desc in INTENT_CATALOGUE.items():
        parts.append(f"- {intent!r}: {desc}")

    # ── Section 6: Output JSON schema ─────────────────────────────────────
    parts.append("\n## ФОРМАТ ОТВЕТА — строго JSON, никакого другого текста")
    parts.append(
        json.dumps(
            {
                "intent":      "<один из интентов выше>",
                "entities": {
                    "fuel_volume":      "<число литров или null>",
                    "hours":            "<число часов или null>",
                    "reg_number":       "<номер машины если явно указан, иначе null>",
                    "description":      "<описание проблемы если issue_report>",
                    "severity":         "<info | warning | high | critical>",
                    "component":        "<компонент машины: engine/hydraulics/tracks/bucket/...>",
                    "symptom":          "<симптом: leak/noise/smoke/no_start/overheat/...>",
                    "production_qty":   "<число выработки или null>",
                    "production_unit":  "<кубов/рейсов/тонн или null>",
                    "notes":            "<прочие детали или null>",
                },
                "missing_fields":  ["<поля которых не хватает для записи>"],
                "confidence":      0.95,
                "reasoning":       "<одно предложение — почему выбрал этот интент>",
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    # ── Section 7: Positive examples ──────────────────────────────────────
    parts.append("\n## ПРИМЕРЫ ПРАВИЛЬНОГО ИЗВЛЕЧЕНИЯ")
    parts.append(
        '«залил 50» (активная смена на КАТ-101) → '
        '{"intent":"fuel_log","entities":{"fuel_volume":50},"missing_fields":[],"confidence":0.97}'
    )
    parts.append(
        '«наработка 8ч» → '
        '{"intent":"hours_log","entities":{"hours":8},"missing_fields":[],"confidence":0.95}'
    )
    parts.append(
        '«стучит движок» → '
        '{"intent":"issue_report","entities":{"component":"engine","symptom":"noise",'
        '"description":"стучит двигатель","severity":"warning"},"missing_fields":[],"confidence":0.82}'
    )
    parts.append(
        '«50» (нет активной смены, непонятный контекст) → '
        '{"intent":"clarification_needed","entities":{},'
        '"missing_fields":["context"],"confidence":0.20}'
    )

    # ── Section 8: Hallucination guardrails ────────────────────────────────
    from app.core.model_profiles import patch_forbidden_block
    parts.append("\n## ЗАПРЕЩЕНО")
    parts.append(patch_forbidden_block())

    return "\n".join(parts)


def _format_session_context(session: Optional[SessionContext]) -> str:
    """Format the session as a compact context block for the system prompt."""
    if session is None or session.machine_id is None:
        return (
            "Статус: Активная смена НЕ открыта.\n"
            "Машина: неизвестна.\n"
            "Оператор: неизвестен."
        )

    lines = [
        f"Статус: Активная смена ОТКРЫТА.",
        f"Машина: {session.machine_reg_number or '?'}"
        + (f" ({session.machine_type})" if session.machine_type else ""),
    ]

    if session.shift_started_at:
        mins = session.minutes_on_shift or 0
        h, m = divmod(mins, 60)
        lines.append(f"Смена начата: {session.shift_started_at.strftime('%H:%M')} ({h}ч {m}м назад)")

    if session.fuel_logged_today > 0:
        lines.append(f"Топливо сегодня: {session.fuel_logged_today:.0f}л")

    if session.hours_logged_today > 0:
        lines.append(f"Наработка сегодня: {session.hours_logged_today:.1f}ч")

    if session.open_issue_count > 0:
        lines.append(f"Открытых проблем: {session.open_issue_count}")

    return "\n".join(lines)


def _format_history(history: list[dict[str, Any]]) -> str:
    """Format recent timeline events as a compact chronological summary."""
    if not history:
        return "Нет предыдущих событий в этой смене."

    lines = []
    for event in history[-8:]:   # cap at 8 most recent events
        ts      = event.get("created_at", "")
        etype   = event.get("event_type", "?")
        content = event.get("content", {})
        raw     = event.get("raw_text", "")

        # Format timestamp
        if isinstance(ts, datetime):
            ts_str = ts.strftime("%H:%M")
        elif ts:
            ts_str = str(ts)[:5]
        else:
            ts_str = "--:--"

        # Build a compact summary
        if etype == "FUEL_LOG" and "fuel_volume" in content:
            summary = f"заправка {content['fuel_volume']}л"
        elif etype == "HOURS_LOG" and "hours" in content:
            summary = f"наработка {content['hours']}ч"
        elif etype == "ISSUE_REPORT":
            desc = content.get("description", raw[:50])
            summary = f"проблема: {desc[:60]}"
        elif etype == "SHIFT_START":
            summary = "начало смены"
        elif etype == "SHIFT_END":
            summary = "конец смены"
        else:
            summary = raw[:60] if raw else etype.lower()

        lines.append(f"  {ts_str} — {summary}")

    return "\n".join(lines)


def _build_user_message(update: FleetUpdate) -> str:
    """The user turn: just the operator's sanitised text."""
    return update.raw_text.strip()


# ---------------------------------------------------------------------------
# Clarification prompt builder
# ---------------------------------------------------------------------------

# Templates indexed by intent + missing field combination
_CLARIFICATION_TEMPLATES: dict[str, str] = {
    "fuel_log:fuel_volume":
        "Сколько литров залили?",
    "hours_log:hours":
        "Сколько часов наработки?",
    "issue_report:description":
        "Опишите подробнее — что именно случилось?",
    "shift_start:reg_number":
        "На какой машине начинаете смену? Укажите номер.",
    "production_log:production_qty":
        "Сколько {unit} сделали?",
    "machine_switch:reg_number":
        "На какую машину переходите? Укажите номер.",
    "parts_request:description":
        "Какая запчасть нужна?",
    # Fallback for any combination
    "_default":
        "Не хватает данных: {fields}. Уточните, пожалуйста.",
}


def build_clarification_reply(
    intent:         str,
    missing_fields: list[str],
    context:        Optional[SessionContext] = None,
) -> str:
    """
    Build a natural Russian clarification message to send to the operator.
    Prefers specific templates over the generic fallback.
    """
    if not missing_fields:
        return ""

    # Try specific template for each missing field
    for field in missing_fields:
        key = f"{intent}:{field}"
        if key in _CLARIFICATION_TEMPLATES:
            return _CLARIFICATION_TEMPLATES[key]

    # Generic fallback
    field_names_ru = {
        "fuel_volume":     "объём топлива",
        "hours":           "количество часов",
        "reg_number":      "номер машины",
        "description":     "описание проблемы",
        "production_qty":  "объём выработки",
        "production_unit": "единицу измерения",
        "notes":           "пояснение",
    }
    translated = [field_names_ru.get(f, f) for f in missing_fields]
    return _CLARIFICATION_TEMPLATES["_default"].format(
        fields=", ".join(translated)
    )


# ---------------------------------------------------------------------------
# Conversation history summarisation prompt
# ---------------------------------------------------------------------------

def build_history_summary_prompt(
    history:      list[dict[str, Any]],
    machine_reg:  str,
    max_chars:    int = 600,
) -> tuple[str, str]:
    """
    Build a prompt that summarises a full shift's worth of events into
    a compact paragraph suitable for injection into the context window.

    Returns (system_prompt, user_message).
    Used by the Watcher to pre-compute summaries for long-running shifts.
    """
    system = (
        "Составь краткое резюме смены для машины на основе журнала событий.\n"
        "Резюме должно быть 2-3 предложения на русском языке.\n"
        "Включи: общую наработку, топливо, количество проблем, текущий статус.\n"
        "Не добавляй ничего кроме резюме."
    )

    events_text = "\n".join(
        f"- {e.get('event_type','?')}: {json.dumps(e.get('content',{}), ensure_ascii=False)}"
        for e in history
    )
    user = (
        f"Машина: {machine_reg}\n"
        f"События смены:\n{events_text[:max_chars]}"
    )

    return system, user


# ---------------------------------------------------------------------------
# Missing-field detector (deterministic — does not require LLM)
# ---------------------------------------------------------------------------

def detect_missing_fields(intent: str, entities: dict[str, Any]) -> list[str]:
    """
    Given an intent and the extracted entities, return the list of fields
    that are required but absent or null.

    This is deterministic — no LLM needed. Runs after LLM extraction to
    decide whether to write to DB or ask the operator for clarification.
    """
    required = REQUIRED_ENTITIES.get(intent, [])
    return [
        field for field in required
        if entities.get(field) is None or entities.get(field) == ""
    ]


def validate_numeric_fields(entities: dict[str, Any]) -> list[str]:
    """
    Returns a list of field names where a numeric value was expected
    but the LLM returned a non-numeric value.

    E.g. fuel_volume = "пятьдесят" instead of 50 → validation failure.
    """
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
