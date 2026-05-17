"""
app/core/intelligence_router.py
================================
Four-stage intelligence pipeline for VFM.

Stage 1 — Continuity check (deterministic)
Stage 2 — Intent classification (fine-tuned DistilBERT or LLM fallback)
Stage 3 — NER extraction (fine-tuned DistilBERT or LLM fallback)
Stage 4 — Agency LLM response generation

The pipeline degrades gracefully:
  - Both models loaded  → Stage 2 + 3 use models, Stage 4 uses LLM for response
  - Classifier only     → Stage 2 uses model, Stage 3+4 use LLM
  - No models           → Stages 2+3 use LLM (current behaviour)

ExtractionResult is the contract between Intelligence and Agency layers.
The agency LLM always receives the same structured input regardless of
which path produced the extraction.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

import aiohttp

from app.core.model_loader import get_classifier, get_ner, models_ready
from app.schemas.fleet_update import FleetUpdate, SessionContext
from app.core.task_router import route as task_route
from app.core.persona import load_persona, get_persona_summary
from app.core.context_graph import build_context_graph, serialise_for_prompt

logger = logging.getLogger(__name__)

# ── Confidence routing thresholds ─────────────────────────────────────────────
CONF_AUTO    = 0.85   # write without asking
CONF_CONFIRM = 0.60   # write but echo back for confirmation

# ── Non-operational intents — no extraction, agency handles directly ───────────
NON_OPERATIONAL = {"off_topic", "clarification_response", "status_update"}

# ── Slots relevant per intent — narrows NER extraction surface ────────────────
INTENT_SLOTS: dict[str, set[str]] = {
    "shift_start":    {"reg_number", "alias"},
    "shift_end":      set(),
    "fuel_log":       {"fuel_volume", "unit", "reg_number"},
    "hours_log":      {"hours", "unit", "reg_number"},
    "issue_report":   {"description", "component", "symptom", "severity", "reg_number"},
    "production_log": {"production_qty", "production_unit"},
    "parts_request":  {"description"},
    "handover_note":  {"name", "notes"},
    "machine_switch": {"reg_number", "alias"},
    "inspection_check": set(),
    "multi_intent":   {"fuel_volume", "hours", "unit", "description", "component"},
}


# ── Subword reassembly ────────────────────────────────────────────────────────

def _reassemble(ner_output: list) -> dict[str, str]:
    """Merge consecutive same-group ## subword fragments into whole words."""
    if not ner_output:
        return {}
    entities: dict[str, dict] = {}
    current_group = None
    current_word  = ""
    current_score = 0.0
    count         = 0
    for item in ner_output:
        group = item["entity_group"]
        word  = item["word"]
        score = float(item["score"])
        if group == current_group:
            current_word  += word.replace("##", "")
            current_score += score
            count         += 1
        else:
            if current_group:
                entities[current_group.lower()] = {
                    "word": current_word, "score": current_score / count
                }
            current_group = group
            current_word  = word.replace("##", "")
            current_score = score
            count         = 1
    if current_group:
        entities[current_group.lower()] = {
            "word": current_word, "score": current_score / count
        }
    return {k: v["word"] for k, v in entities.items()}


# ── ExtractionResult ─────────────────────────────────────────────────────────

@dataclass
class ExtractionResult:
    intent:           str
    entities:         dict[str, Any]    = field(default_factory=dict)
    missing_fields:   list[str]         = field(default_factory=list)
    confidence:       float             = 0.0
    confidence_route: str              = "llm"   # auto | confirm | llm
    via_classifier:   bool             = False
    via_ner:          bool             = False
    clarification:    Optional[str]    = None
    errors:           list[str]        = field(default_factory=list)


# ── Stage 1 — Continuity check ───────────────────────────────────────────────

def _check_continuity(update: FleetUpdate, session: Optional[SessionContext]) -> str:
    """
    Returns: 'clarification_response' | 'active_session' | 'no_session'
    Deterministic — no model needed.
    """
    if session and getattr(session, "pending_clarification_field", None):
        return "clarification_response"
    if session and session.machine_id:
        return "active_session"
    return "no_session"


# ── Stage 2 — Intent classification ─────────────────────────────────────────

def _classify_intent(text: str) -> tuple[str, float, bool]:
    """
    Returns (intent, confidence, via_classifier).
    Falls back to ('unknown', 0.0, False) if classifier not loaded.
    """
    clf, labels = get_classifier()
    if clf is None:
        return "unknown", 0.0, False

    try:
        result = clf(text)[0]
        return result["label"], float(result["score"]), True
    except Exception as e:
        logger.warning(f"Classifier inference failed: {e}")
        return "unknown", 0.0, False


# ── Stage 3 — NER extraction ─────────────────────────────────────────────────

def _extract_entities(
    text:   str,
    intent: str,
) -> tuple[dict[str, Any], float, bool]:
    """
    Returns (entities, confidence, via_ner).
    Only runs for operational intents.
    Narrows to intent-relevant slots.
    """
    ner, labels, loaded_slots = get_ner()
    if ner is None or intent in NON_OPERATIONAL:
        return {}, 0.0, False

    try:
        raw = ner(text)
        all_entities = _reassemble(raw)

        # Narrow to slots relevant for this intent
        relevant = INTENT_SLOTS.get(intent, set())
        if relevant:
            entities = {k: v for k, v in all_entities.items() if k in relevant}
        else:
            entities = {}

        # Compute aggregate confidence (min of non-O token scores)
        scores = [item["score"] for item in raw if item.get("score", 0) > 0]
        confidence = min(scores) if scores else 0.0

        return entities, float(confidence), True

    except Exception as e:
        logger.warning(f"NER inference failed: {e}")
        return {}, 0.0, False


# ── Stage 4 — Agency LLM response ────────────────────────────────────────────

def _build_agency_prompt(
    update, session, intent, entities,
    missing, confidence, is_proactive,
    task_type: str = "T3",
    context_graph: dict = None,
) -> tuple[str, str]:

    context_graph = context_graph or {}

    # Persona injection — full for deep reasoning, compact for simple
    if task_type in ("T5", "T6", "T7", "T8"):
        persona_block = load_persona()
    else:
        persona_block = get_persona_summary()

    # Context graph summary
    ctx_summary = serialise_for_prompt(context_graph) if context_graph \
                  else _format_session_context_fallback(session)

    # Extraction summary
    entity_summary = ", ".join(
        f"{k}: {v}" for k, v in entities.items() if v is not None
    ) if entities else "нет данных"

    missing_summary = ", ".join(missing) if missing else "нет"
    signals = context_graph.get("signals", {})
    machine = context_graph.get("machine", {})
    machine_name = machine.get("alias") or machine.get("reg_number") or "машина"

    # Task-type-aware instruction
    if task_type == "T4":
        shift = context_graph.get("current_shift", {})
        if shift.get("open_issues", 0) > 0:
            shift_detail = f"{machine_name} — есть открытые проблемы"
        elif shift.get("fuel_rate_today", 0) > 0:
            shift_detail = f"{machine_name} — топливо {shift.get('fuel_logged', 0)}л"
        else:
            shift_detail = machine_name

        instructions = (
            f"Оператор написал не по работе: '{update.raw_text.strip()}'. "
            f"Ответ строго на русском, максимум 2 предложения: "
            f"1) Коротко признай — одно слово или короткая фраза. "
            f"2) Спроси о {shift_detail} — конкретно и коротко. "
            f"Без английских слов. Без длинных предложений."
        )
    elif task_type == "T5":
        anomaly = signals.get("fuel_anomaly") or signals.get("recurring_issue") or "аномалия"
        instructions = (
            f"VFM заметил: {anomaly}. "
            "Задай оператору один конкретный вопрос об этом. "
            "Упомяни конкретные цифры из контекста. Не обвиняй — спрашивай."
        )
    elif task_type == "T6":
        pattern = signals.get("recurring_issue", "повторная проблема")
        instructions = (
            f"Паттерн: {pattern}. "
            "Одно предложение — наблюдение с цифрами. "
            "Одно предложение — конкретная рекомендация."
        )
    elif task_type == "T3":
        instructions = (
            f"Данные: {entity_summary}. Не хватает: {missing_summary}. "
            "Используй контекст сессии. Задай один точный вопрос. "
            "Не спрашивай то, что уже есть в контексте."
        )
    elif task_type == "T7":
        instructions = (
            "Составь краткое резюме смены для владельца. "
            "Формат: машина — статус, топливо, наработка, проблемы. "
            "Только аномалии и требующее внимания."
        )
    elif task_type == "T8":
        instructions = (
            "Срочное уведомление владельцу. "
            "Одно предложение — ситуация. Одно — почему важно. "
            "Одно — рекомендация к действию."
        )
    else:
        instructions = "Ответь коротко и по делу."

    system = (
        f"{persona_block}\n\n"
        f"---\n\n"
        f"ТЕКУЩАЯ МАШИНА: {machine_name}\n"
        f"КОНТЕКСТ СМЕНЫ: {ctx_summary}\n\n"
        f"ЗАДАЧА: {instructions}\n\n"
        f"ВАЖНО: В ответе обязательно упомяни '{machine_name}'."
    )

    user = update.raw_text.strip() if not is_proactive \
           else f"[VFM инициирует — {task_type}]"

    return system, user


def _format_session_context_fallback(session) -> str:
    """Fallback when context graph is unavailable."""
    if not session or not getattr(session, 'machine_id', None):
        return "Активная смена не найдена."
    machine = getattr(session, 'machine_alias', None) \
              or getattr(session, 'machine_reg_number', '?')
    return f"Машина: {machine}. Смена активна."


async def _call_agency_llm(system: str, user: str) -> str:
    """Call the agency LLM. Returns natural Russian reply text."""
    import os
    from app.core.model_profiles import ollama_options

    provider  = os.getenv("LLM_PROVIDER", "ollama").lower()
    base_url  = os.getenv("LLM_BASE_URL", "http://localhost:11434")
    model     = os.getenv("LLM_MODEL", "qwen2.5:3b-instruct")
    timeout   = int(os.getenv("LLM_TIMEOUT_SECONDS", "60"))
    api_key   = os.getenv("LLM_API_KEY", "")

    payload: dict[str, Any]

    if provider == "ollama":
        payload = {
            "model":   model,
            "stream":  False,
            "options": {
                **ollama_options(),
                "num_predict":    120,
                "repeat_penalty": 1.15,
                "stop":           ["。", "的", "<|im_end|>"],
            },
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
        }
        url = f"{base_url}/v1/chat/completions"
        headers = {"Content-Type": "application/json"}
    else:
        # Anthropic / OpenAI-compatible
        payload = {
            "model": model,
            "max_tokens": 200,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        url = f"{base_url}/v1/messages"
        headers = {
            "Content-Type":      "application/json",
            "x-api-key":         api_key,
            "anthropic-version": "2023-06-01",
        }

    async with aiohttp.ClientSession() as http:
        async with http.post(
            url, json=payload, headers=headers,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            data = await resp.json()

    # Extract text from response
    if provider == "ollama":
        response_text = data["choices"][0]["message"]["content"].strip()
        # Strip Qwen3 thinking blocks if present
        response_text = re.sub(r'<think>.*?</think>', '', response_text, flags=re.DOTALL).strip()

        logger.info(f"[LLM] system_len={len(system.split())} tokens")
        logger.info(f"[LLM] user: {user[:80]}")
        logger.info(f"[LLM] reply: {response_text[:120]}")

        return response_text
    else:
        return data["content"][0]["text"].strip()


# ── Main entry point ──────────────────────────────────────────────────────────

async def run_intelligence(
    update:         FleetUpdate,
    session:        Optional[SessionContext],
    recent_history: list[dict] | None = None,
    is_proactive:   bool = False,
    db=None,
) -> ExtractionResult:
    """
    Four-stage intelligence pipeline.
    Returns ExtractionResult consumed by event_processor.
    """
    mode          = models_ready()["mode"]
    text          = update.raw_text.strip()
    result        = ExtractionResult(intent="unknown")
    context_graph = {}

    # ── Stage 1: Continuity ───────────────────────────────────────────────────
    continuity = _check_continuity(update, session)
    if continuity == "clarification_response" and not is_proactive:
        result.intent           = "clarification_response"
        result.confidence       = 0.95
        result.confidence_route = "auto"
        # Agency LLM handles the clarification response naturally
        try:
            system, user = _build_agency_prompt(
                update, session, "clarification_response",
                {}, [], 0.95
            )
            result.clarification = await _call_agency_llm(system, user)
        except Exception as e:
            result.errors.append(str(e))
            result.clarification = "Понял. Записываю."
        return result

    # Build context graph — living machine memory
    if session and getattr(session, 'machine_id', None) and getattr(session, 'operator_id', None):
        try:
            context_graph = await build_context_graph(
                machine_id  = session.machine_id,
                operator_id = session.operator_id,
                session_ctx = session,
                db          = db,
            )
            object.__setattr__(update, '_context_graph', context_graph)
        except Exception as e:
            logger.warning(f"Context graph failed: {e}")

    # ── Stage 2: Intent classification ───────────────────────────────────────
    if mode in ("full", "clf+llm"):
        intent, clf_conf, via_clf = _classify_intent(text)
        result.via_classifier = via_clf
    else:
        intent, clf_conf, via_clf = "unknown", 0.0, False

    # ── Stage 3: NER extraction ───────────────────────────────────────────────
    entities  = {}
    ner_conf  = 0.0
    via_ner   = False

    if mode == "full" and intent != "unknown" and intent not in NON_OPERATIONAL:
        entities, ner_conf, via_ner = _extract_entities(text, intent)
        result.via_ner = via_ner

    # ── LLM fallback for extraction when models unavailable or low confidence ─
    need_llm_extraction = (
        mode == "llm_only"
        or intent == "unknown"
        #or (intent not in NON_OPERATIONAL and ner_conf < CONF_CONFIRM and not entities)
    )

    if need_llm_extraction:
        try:
            from app.core.context_llm import context_extract
            llm_result = await context_extract(update, session, recent_history)
            intent     = llm_result.intent or intent
            entities   = llm_result.entities or entities
            clf_conf   = llm_result.confidence
            result.missing_fields = llm_result.missing_fields or []
            result.clarification  = llm_result.clarification
        except Exception as e:
            logger.error(f"LLM extraction fallback failed: {e}")
            result.errors.append(str(e))

    # ── Determine missing fields ──────────────────────────────────────────────
    if not result.missing_fields:
        from app.core.context_prompt import detect_missing_fields
        result.missing_fields = detect_missing_fields(intent, entities)

    # ── Compute confidence route ──────────────────────────────────────────────
    effective_conf = clf_conf if entities else min(clf_conf, ner_conf) if ner_conf > 0 else clf_conf
    if effective_conf >= CONF_AUTO and not result.missing_fields:
        route = "auto"
    elif effective_conf >= CONF_CONFIRM:
        route = "confirm"
    else:
        route = "llm"

    result.intent           = intent
    result.entities         = entities
    result.confidence       = effective_conf
    result.confidence_route = route

    # ── Stage 4: Agency response via TaskRouter ───────────────────────────
    if not result.clarification:
        decision = task_route(
            intent         = intent,
            entities       = entities,
            missing_fields = result.missing_fields,
            confidence     = effective_conf,
            session        = session,
            context_graph  = context_graph,
            is_proactive   = is_proactive,
            recipient      = "operator",
        )

        if not decision.needs_llm:
            result.clarification = decision.reply
            logger.info(f"[Router] {decision.task_type} → template")
        else:
            try:
                system, user = _build_agency_prompt(
                    update, session, intent, entities,
                    result.missing_fields, effective_conf,
                    is_proactive, decision.task_type,
                    context_graph,
                )
                result.clarification = await _call_agency_llm(system, user)
                logger.info(f"[Router] {decision.task_type} → LLM")
            except Exception as e:
                logger.error(f"Agency LLM failed: {e}")
                result.errors.append(str(e))
                result.clarification = _template_fallback(
                    intent, entities, result.missing_fields
                )

    return result


def _template_fallback(intent: str, entities: dict, missing: list) -> str:
    """Emergency fallback when agency LLM times out."""
    if missing:
        field_ru = {
            "fuel_volume":    "сколько литров",
            "hours":          "сколько часов",
            "reg_number":     "номер машины",
            "description":    "что именно случилось",
            "production_qty": "сколько",
        }
        q = field_ru.get(missing[0], missing[0])
        return f"Уточни: {q}?"
    if intent == "fuel_log" and "fuel_volume" in entities:
        return f"Записал: {entities['fuel_volume']}л топлива ✓"
    if intent == "hours_log" and "hours" in entities:
        return f"Записал: {entities['hours']}ч наработки ✓"
    if intent == "shift_start":
        return "Смена открыта ✓"
    if intent == "shift_end":
        return "Смена закрыта ✓"
    if intent == "off_topic":
        return "Понял! Если что по машине — пиши."
    return "Принято ✓"
