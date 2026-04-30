"""
app/core/context_llm.py

The new Intelligence layer. Replaces ner_handler.py + llm_fallback.py.

Public interface (matches what EventProcessor._run_intelligence expects):

    result = await context_extract(update, session, recent_history)

Returns a validated ExtractionResult with:
    intent          — Intent enum value
    entities        — dict of extracted fields (numeric fields are floats)
    missing_fields  — required fields that were absent in this message
    confidence      — 0.0-1.0
    via_llm         — always True (this layer always uses LLM)
    guard_result    — GuardResult from injection check
    errors          — list of strings for audit

Pipeline inside this module:
    1. Injection guard    — block/sanitise adversarial inputs
    2. Prompt builder     — inject session context + history
    3. LLM call           — multi-provider (Anthropic / YandexGPT / Ollama)
    4. Response validator — parse + type-check + fix numeric fields
    5. Missing-field check — deterministic, no LLM needed
    6. Confidence calibration — adjust confidence based on validation results
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Optional

import aiohttp

from app.core.context_prompt import (
    build_extraction_prompt,
    build_clarification_reply,
    detect_missing_fields,
    validate_numeric_fields,
    NUMERIC_FIELDS,
)
from app.core.injection_guard import GuardResult, check as guard_check
from app.schemas.fleet_update import (
    ConfidenceRoute, FleetUpdate, Intent, SessionContext, Severity,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic")
LLM_API_KEY  = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.anthropic.com")
LLM_MODEL    = os.getenv("LLM_MODEL", "claude-haiku-4-5-20251001")
LLM_TIMEOUT  = int(os.getenv("LLM_TIMEOUT_SECONDS", "12"))

# Confidence thresholds — same as the existing pipeline
CONF_AUTO    = 0.85
CONF_CONFIRM = 0.60

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class ExtractionResult:
    intent:         Intent
    entities:       dict[str, Any]        = field(default_factory=dict)
    missing_fields: list[str]             = field(default_factory=list)
    confidence:     float                 = 0.0
    confidence_route: ConfidenceRoute     = ConfidenceRoute.LLM
    via_llm:        bool                  = True
    guard_result:   Optional[GuardResult] = None
    clarification:  Optional[str]         = None   # reply to send if fields missing
    errors:         list[str]             = field(default_factory=list)
    raw_llm_output: str                   = ""     # for debugging


# ---------------------------------------------------------------------------
# LLM provider adapters
# ---------------------------------------------------------------------------

async def _call_anthropic(
    system: str, user: str, session: aiohttp.ClientSession
) -> str:
    payload = {
        "model":      LLM_MODEL,
        "max_tokens": 600,
        "system":     system,
        "messages":   [{"role": "user", "content": user}],
        "temperature": 0.0,   # zero temp for deterministic extraction
    }
    async with session.post(
        f"{LLM_BASE_URL}/v1/messages",
        json=payload,
        headers={
            "x-api-key":         LLM_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type":      "application/json",
        },
        timeout=aiohttp.ClientTimeout(total=LLM_TIMEOUT),
    ) as resp:
        resp.raise_for_status()
        data = await resp.json()
        return data["content"][0]["text"]


async def _call_yandex(
    system: str, user: str, session: aiohttp.ClientSession
) -> str:
    folder_id = os.getenv("YANDEX_FOLDER_ID", "")
    payload = {
        "modelUri": f"gpt://{folder_id}/yandexgpt-lite",
        "completionOptions": {"temperature": 0.0, "maxTokens": 600},
        "messages": [
            {"role": "system", "text": system},
            {"role": "user",   "text": user},
        ],
    }
    async with session.post(
        "https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
        json=payload,
        headers={
            "Authorization": f"Api-Key {LLM_API_KEY}",
            "content-type":  "application/json",
        },
        timeout=aiohttp.ClientTimeout(total=LLM_TIMEOUT),
    ) as resp:
        resp.raise_for_status()
        data = await resp.json()
        return data["result"]["alternatives"][0]["message"]["text"]


async def _call_ollama(
    system: str, user: str, session: aiohttp.ClientSession
) -> str:
    from app.core.model_profiles import ollama_options
    payload = {
        "model":   LLM_MODEL,
        "stream":  False,
        "options": ollama_options(),
        "messages": [
            {"role": "system",  "content": system},
            {"role": "user",    "content": user},
        ],
    }
    async with session.post(
        f"{LLM_BASE_URL}/v1/chat/completions",
        json=payload,
        timeout=aiohttp.ClientTimeout(total=LLM_TIMEOUT),
    ) as resp:
        resp.raise_for_status()
        data = await resp.json()
        return data["choices"][0]["message"]["content"]


async def _call_llm(system: str, user: str) -> str:
    """Route to the configured provider."""
    async with aiohttp.ClientSession() as http:
        if LLM_PROVIDER == "yandex":
            return await _call_yandex(system, user, http)
        elif LLM_PROVIDER == "ollama":
            return await _call_ollama(system, user, http)
        else:
            return await _call_anthropic(system, user, http)


# ---------------------------------------------------------------------------
# Response validator
# ---------------------------------------------------------------------------

def _strip_fences(raw: str) -> str:
    """Remove markdown code fences if the LLM wrapped the JSON."""
    stripped = raw.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.MULTILINE)
        stripped = re.sub(r"\s*```$", "", stripped, flags=re.MULTILINE)
    return stripped.strip()


def _coerce_numeric(entities: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """
    Convert numeric fields to float. If the LLM returned a string like
    "пятьдесят" or "50л", try to extract the number; on failure, set to
    None and return the field name in the failures list.
    """
    _NUM_RE = re.compile(r"(\d+(?:[.,]\d+)?)")
    coerced  = dict(entities)
    failures = []

    for field_name in NUMERIC_FIELDS:
        val = coerced.get(field_name)
        if val is None:
            continue
        if isinstance(val, (int, float)):
            coerced[field_name] = float(val)
            continue
        # String — try to extract a number
        match = _NUM_RE.search(str(val))
        if match:
            coerced[field_name] = float(match.group(1).replace(",", "."))
        else:
            logger.warning(
                f"[ContextLLM] Could not coerce {field_name}={val!r} to float — setting null"
            )
            coerced[field_name] = None
            failures.append(field_name)

    return coerced, failures


def _parse_and_validate(raw_text: str) -> tuple[dict[str, Any], list[str]]:
    """
    Parse the LLM response JSON and return (parsed_dict, validation_errors).
    """
    errors: list[str] = []
    cleaned = _strip_fences(raw_text)

    # Find the first '{' — model sometimes adds a sentence before the JSON
    brace_start = cleaned.find("{")
    if brace_start > 0:
        cleaned = cleaned[brace_start:]

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as e:
        errors.append(f"JSON parse error: {e} — raw: {cleaned[:120]}")
        return {}, errors

    # Ensure required top-level keys
    parsed.setdefault("intent",        "unknown")
    parsed.setdefault("entities",      {})
    parsed.setdefault("missing_fields", [])
    parsed.setdefault("confidence",    0.5)
    parsed.setdefault("reasoning",     "")

    # Validate confidence is a number in [0, 1]
    try:
        conf = float(parsed["confidence"])
        parsed["confidence"] = max(0.0, min(1.0, conf))
    except (ValueError, TypeError):
        parsed["confidence"] = 0.5
        errors.append("LLM returned non-numeric confidence")

    # Coerce numeric entity fields
    if isinstance(parsed.get("entities"), dict):
        parsed["entities"], coerce_failures = _coerce_numeric(parsed["entities"])
        for f in coerce_failures:
            errors.append(f"Numeric coercion failed for {f!r}")

    # Ensure entities is a dict (not None, not a string)
    if not isinstance(parsed.get("entities"), dict):
        parsed["entities"] = {}
        errors.append("LLM returned non-dict entities — reset to empty")

    return parsed, errors


def _map_intent(raw: str) -> Intent:
    try:
        return Intent(raw)
    except ValueError:
        return Intent.UNKNOWN


def _map_severity(raw: Optional[str]) -> Optional[Severity]:
    if raw is None:
        return None
    try:
        return Severity(raw)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Confidence calibration
# ---------------------------------------------------------------------------

def _calibrate_confidence(
    base_confidence:   float,
    intent:            Intent,
    missing_fields:    list[str],
    coerce_failures:   list[str],
    guard_suspicious:  bool,
) -> float:
    """
    Adjust the LLM's self-reported confidence based on observable signals.
    The LLM tends to over-report confidence; this brings it closer to reality.
    """
    conf = base_confidence

    # Missing required fields — operator will need to answer a follow-up
    if missing_fields:
        conf -= 0.10 * len(missing_fields)

    # Numeric coercion failures — model returned something it couldn't parse
    if coerce_failures:
        conf -= 0.15 * len(coerce_failures)

    # Unknown intent — model couldn't classify
    if intent == Intent.UNKNOWN:
        conf = min(conf, 0.30)

    # Clarification intent — model explicitly said it doesn't know
    if intent == Intent.CLARIFICATION:
        conf = min(conf, 0.40)

    # Suspicious input flagged by guard
    if guard_suspicious:
        conf -= 0.10

    return max(0.0, min(1.0, round(conf, 3)))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def context_extract(
    update:         FleetUpdate,
    session:        Optional[SessionContext],
    recent_history: list[dict[str, Any]] | None = None,
) -> ExtractionResult:
    """
    Main entry point. Called by EventProcessor._run_intelligence.

    1. Run injection guard on raw_text
    2. Build context-aware prompt
    3. Call LLM
    4. Parse + validate response
    5. Detect missing fields
    6. Calibrate confidence
    7. Return ExtractionResult
    """
    errors: list[str] = []

    # ── Step 1: Injection guard ────────────────────────────────────────────
    guard = guard_check(update.raw_text)

    if not guard.passed:
        logger.warning(
            f"[ContextLLM] Input blocked by guard: {guard.reason!r} "
            f"operator={update.operator_id}"
        )
        return ExtractionResult(
            intent        = Intent.UNKNOWN,
            confidence    = 0.0,
            guard_result  = guard,
            errors        = [f"Injection guard blocked: {guard.reason}"],
            clarification = "Сообщение не распознано. Пожалуйста, опишите ситуацию своими словами.",
        )

    if guard.was_truncated:
        errors.append(f"Input truncated from {guard.original_length} to {len(guard.sanitised_text)} chars")

    # Use the sanitised text for all downstream processing
    sanitised_text = guard.sanitised_text

    # ── Step 2: Check LLM is configured ────────────────────────────────────
    if not LLM_API_KEY and LLM_PROVIDER != "ollama":
        logger.warning("[ContextLLM] LLM_API_KEY not set")
        return ExtractionResult(
            intent     = Intent.UNKNOWN,
            confidence = 0.0,
            errors     = ["LLM_API_KEY not configured"],
            guard_result = guard,
        )

    # ── Step 3: Build context-aware prompt ────────────────────────────────
    # Temporarily swap raw_text with sanitised version for prompt building
    original_raw    = update.raw_text
    update.raw_text = sanitised_text
    system_prompt, user_message = build_extraction_prompt(
        update         = update,
        session        = session,
        recent_history = recent_history,
    )
    update.raw_text = original_raw   # restore

    # ── Step 4: Call LLM ──────────────────────────────────────────────────
    try:
        raw_response = await _call_llm(system_prompt, user_message)
    except aiohttp.ClientError as e:
        logger.error(f"[ContextLLM] HTTP error: {e}")
        return ExtractionResult(
            intent     = Intent.UNKNOWN,
            confidence = 0.0,
            errors     = [f"LLM HTTP error: {e}"],
            guard_result = guard,
        )
    except Exception as e:
        logger.error(f"[ContextLLM] Unexpected error: {e}")
        return ExtractionResult(
            intent     = Intent.UNKNOWN,
            confidence = 0.0,
            errors     = [str(e)],
            guard_result = guard,
        )

    # ── Step 5: Parse + validate ──────────────────────────────────────────
    parsed, parse_errors = _parse_and_validate(raw_response)
    errors.extend(parse_errors)

    intent   = _map_intent(parsed.get("intent", "unknown"))
    entities = parsed.get("entities", {})
    llm_conf = float(parsed.get("confidence", 0.5))

    # Pull severity into entities if present
    sev_raw = entities.pop("severity", None)
    if sev_raw:
        entities["severity"] = sev_raw

    # ── Step 6: Detect missing fields ─────────────────────────────────────
    # Combine LLM-reported missing with our own deterministic check
    llm_missing  = parsed.get("missing_fields") or []
    det_missing  = detect_missing_fields(intent.value, entities)
    missing      = list(dict.fromkeys(llm_missing + det_missing))   # dedup, preserve order

    # Numeric coercion failures already caught in _parse_and_validate;
    # add those fields to missing if they ended up null
    coerce_failures = validate_numeric_fields(entities)

    # ── Step 7: Calibrate confidence ──────────────────────────────────────
    confidence = _calibrate_confidence(
        base_confidence  = llm_conf,
        intent           = intent,
        missing_fields   = missing,
        coerce_failures  = coerce_failures,
        guard_suspicious = (guard.threat_level == "suspicious"),
    )

    # ── Step 8: Determine route ───────────────────────────────────────────
    if intent in (Intent.ADD_MACHINE, Intent.ASSIGN_MACHINE):
        route = ConfidenceRoute.AUTO
    elif confidence >= CONF_AUTO:
        route = ConfidenceRoute.AUTO
    elif confidence >= CONF_CONFIRM:
        route = ConfidenceRoute.CONFIRM
    else:
        route = ConfidenceRoute.LLM   # will trigger re-ask

    # ── Step 9: Build clarification if needed ─────────────────────────────
    clarification = None
    if missing:
        clarification = build_clarification_reply(
            intent  = intent.value,
            missing_fields = missing,
            context = session,
        )

    logger.info(
        f"[ContextLLM] intent={intent.value} conf={confidence:.2f} "
        f"route={route.value} missing={missing} "
        f"guard={guard.threat_level}"
    )

    return ExtractionResult(
        intent           = intent,
        entities         = entities,
        missing_fields   = missing,
        confidence       = confidence,
        confidence_route = route,
        via_llm          = True,
        guard_result     = guard,
        clarification    = clarification,
        errors           = errors,
        raw_llm_output   = raw_response,
    )
