"""
app/core/task_router.py
========================
Deterministic router that classifies each agency interaction into one
of eight task types and handles T1/T2 via templates.

T1 and T2 never touch the LLM — they are faster, cheaper, and more
predictable than any model output for simple confirmations and single
field questions.

T3-T8 are routed to the agency LLM with the appropriate prompt shape
and persona injection.

Task types:
  T1 — Confirmation         (operator logged something, record it)
  T2 — Field clarification  (one specific field missing)
  T3 — Contextual clarify   (ambiguous, needs session reasoning)
  T4 — Off-topic redirect   (non-operational, bridge back)
  T5 — Insight enquiry      (VFM noticed a pattern, asks about it)
  T6 — Proactive suggestion (VFM has enough data to recommend)
  T7 — Shift summary        (owner report at shift end)
  T8 — Owner alert          (owner needs to act on something)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


# ── Intents that produce loggable data points ─────────────────────────────────
LOGGABLE_INTENTS = {
    "fuel_log", "hours_log", "issue_report", "production_log",
    "parts_request", "inspection_check", "handover_note",
    "shift_start", "shift_end", "machine_switch",
}

# ── Fields with known Russian question templates ──────────────────────────────
FIELD_QUESTIONS: dict[str, str] = {
    "fuel_volume":    "Сколько литров?",
    "hours":          "Сколько часов наработки?",
    "reg_number":     "На какой машине? Укажи номер.",
    "description":    "Что именно случилось?",
    "production_qty": "Сколько единиц?",
    "production_unit":"В каких единицах — кубы, рейсы, тонны?",
    "notes":          "Уточни детали.",
}

# ── T1 confirmation templates — shift/admin intents ──────────────────────────
T1_TEMPLATES: dict[str, str] = {
    "shift_start":    "Смена открыта. {machine_name} активна. Удачной смены!",
    "shift_end":      "Смена закрыта. Итоги зафиксированы.",
    "machine_switch": "Переключено на {machine_name} ✓",
    "status_update":  "Понял. Если что по машине — пиши.",
    "handover_note":  "Передача смены записана ✓",
    "clarification_response": "Принято ✓",
}

# ── T2 confirmation templates — data log intents ──────────────────────────────
T2_TEMPLATES: dict[str, str] = {
    "fuel_log":       "Принял, {fuel_volume} литров топлива записал.",
    "hours_log":      "Принял, {hours} часов наработки записал.",
    "issue_report":   "Проблема записана: {description}. Приоритет — {priority}.",
    "production_log": "Записал: {production_qty} {production_unit} ✓",
    "parts_request":  "Запрос зафиксирован: {description}. Передано владельцу.",
    "inspection_check": "Осмотр записан. Замечаний нет ✓",
}

# ── Severity → priority label ─────────────────────────────────────────────────
SEVERITY_PRIORITY = {
    "critical": "КРИТИЧЕСКИЙ",
    "high":     "ВЫСОКИЙ",
    "warning":  "СРЕДНИЙ",
    "info":     "НИЗКИЙ",
}


@dataclass
class RoutingDecision:
    task_type:  str           # T1–T8
    reply:      Optional[str] # set for T1/T2 — no LLM needed
    needs_llm:  bool          # True for T3–T8


def route(
    intent:          str,
    entities:        dict[str, Any],
    missing_fields:  list[str],
    confidence:      float,
    session:         Any,          # SessionContext or None
    context_graph:   dict,         # compact context snapshot
    is_proactive:    bool = False,
    recipient:       str  = "operator",  # "operator" | "owner"
) -> RoutingDecision:
    """
    Determine which task type handles this interaction.
    Returns immediately with a reply for T1/T2 (no LLM).
    Returns needs_llm=True for T3-T8.
    """

    # ── Owner-directed tasks ──────────────────────────────────────────────────
    if recipient == "owner":
        if context_graph.get("is_shift_end_summary"):
            return RoutingDecision("T7", None, True)
        if context_graph.get("requires_owner_action"):
            reply = _build_t8_reply(context_graph, session)
            return RoutingDecision("T8", reply, False)
        return RoutingDecision("T7", None, True)

    # ── Proactive VFM-initiated tasks ─────────────────────────────────────────
    if is_proactive:
        if context_graph.get("recurring_issue"):
            return RoutingDecision("T6", None, True)
        if context_graph.get("anomaly"):
            return RoutingDecision("T5", None, True)
        # Default proactive = check-in
        return RoutingDecision("T5", None, True)

    # ── Off-topic ─────────────────────────────────────────────────────────────
    if intent == "off_topic":
        reply = _build_t4_reply(context_graph, session)
        return RoutingDecision("T4", reply, False)

    # ── T2: single known missing field ───────────────────────────────────────
    if (len(missing_fields) == 1
            and missing_fields[0] in FIELD_QUESTIONS
            and intent in LOGGABLE_INTENTS):
        question = FIELD_QUESTIONS[missing_fields[0]]
        return RoutingDecision("T2", question, False)

    # ── T3: multiple missing fields or ambiguous ──────────────────────────────
    if missing_fields:
        return RoutingDecision("T3", None, True)

    # ── T1/T2: clean extraction, high confidence ─────────────────────────────
    # T1 = shift/admin confirmations, T2 = data log confirmations
    _ALL_TEMPLATES = {**T1_TEMPLATES, **T2_TEMPLATES}
    if (confidence >= 0.85
            and not missing_fields
            and intent in _ALL_TEMPLATES):
        reply = _build_t1_reply(intent, entities, session, context_graph)
        if reply:
            t = "T2" if intent in T2_TEMPLATES else "T1"
            return RoutingDecision(t, reply, False)

    # ── T3 fallback: LLM handles ambiguous cases ─────────────────────────────
    return RoutingDecision("T3", None, True)


def _build_t1_reply(
    intent:       str,
    entities:     dict[str, Any],
    session:      Any,
    context_graph: dict,
) -> Optional[str]:
    """
    Build a T1 template reply. Returns None if template cannot be filled.
    """
    template = T1_TEMPLATES.get(intent) or T2_TEMPLATES.get(intent)
    if not template:
        return None

    # Build the substitution dict
    subs: dict[str, str] = {}

    # Machine name — prefer alias over reg_number
    if session:
        subs["machine_name"] = (
            getattr(session, "machine_alias", None)
            or getattr(session, "machine_reg_number", None)
            or "машина"
        )
    else:
        subs["machine_name"] = entities.get("reg_number", "машина")

    # Entity values
    if "fuel_volume" in entities:
        vol = entities["fuel_volume"]
        subs["fuel_volume"] = str(int(float(vol))) if vol else "?"

    if "hours" in entities:
        hrs = entities["hours"]
        try:
            h = float(hrs)
            subs["hours"] = str(int(h)) if h == int(h) else str(h)
        except (ValueError, TypeError):
            subs["hours"] = str(hrs)

    if "production_qty" in entities:
        subs["production_qty"] = str(entities["production_qty"])
    if "production_unit" in entities:
        subs["production_unit"] = str(entities["production_unit"])
    if "description" in entities:
        desc = str(entities["description"])
        subs["description"] = desc[:60] + ("..." if len(desc) > 60 else "")
    if "notes" in entities:
        subs["notes"] = str(entities["notes"])[:60]

    # Issue priority
    severity = entities.get("severity", "warning")
    subs["priority"] = SEVERITY_PRIORITY.get(str(severity).lower(), "СРЕДНИЙ")

    try:
        return template.format(**subs)
    except KeyError:
        # Template has a field we could not fill — fall through to LLM
        return None


def _build_t4_reply(context_graph: dict, session: Any) -> str:
    """T4: off-topic redirect — steer operator back to machine context."""
    machine = context_graph.get("machine", {})
    machine_name = (
        machine.get("alias") or machine.get("reg_number")
        or (getattr(session, "machine_alias", None) if session else None)
        or (getattr(session, "machine_reg_number", None) if session else None)
        or "машина"
    )
    shift = context_graph.get("current_shift", {})
    if shift.get("open_issues", 0) > 0:
        return f"Понял! Как {machine_name}? Есть открытые проблемы."
    fuel = shift.get("fuel_logged", 0) or 0
    if fuel > 0:
        return f"Понял! Как {machine_name}? Уже залито {int(fuel)}л."
    return f"Понял. Если что по {machine_name} — пиши."


def _build_t8_reply(context_graph: dict, session: Any) -> str:
    """T8: owner alert — concise notification requiring action."""
    machine = context_graph.get("machine", {})
    machine_name = machine.get("alias") or machine.get("reg_number") or "машина"
    signals = context_graph.get("signals", {})
    if signals.get("fuel_anomaly"):
        return f"⚠️ {machine_name}: аномалия топлива. Требует вашей проверки."
    if signals.get("recurring_issue"):
        return f"⚠️ {machine_name}: повторная проблема. Требует вашего внимания."
    alert = context_graph.get("requires_owner_action")
    if isinstance(alert, str) and alert:
        return f"⚠️ {machine_name}: {alert}. Требует вашего действия."
    return f"⚠️ {machine_name}: требует вашего внимания."
