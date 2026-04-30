"""
app/core/llm_fallback.py  — Hour 3

Called when NER confidence < 0.60.
Returns a structured FleetUpdate-compatible dict using an LLM.

Designed to work with any OpenAI-compatible API:
  - Anthropic Claude (default, via API key)
  - YandexGPT (set LLM_PROVIDER=yandex in env)
  - Local Ollama / vLLM (set LLM_PROVIDER=ollama, LLM_BASE_URL=http://localhost:11434)

The prompt is engineered for Russian fleet language and returns
strict JSON matching the FleetUpdate Intelligence block fields.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

import aiohttp

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config — all from env, no hardcoded secrets
# ---------------------------------------------------------------------------
LLM_PROVIDER  = os.getenv("LLM_PROVIDER", "anthropic")   # anthropic | yandex | ollama
LLM_API_KEY   = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL  = os.getenv("LLM_BASE_URL", "https://api.anthropic.com")
LLM_MODEL     = os.getenv("LLM_MODEL", "claude-haiku-4-5-20251001")
LLM_TIMEOUT   = int(os.getenv("LLM_TIMEOUT_SECONDS", "10"))

# ---------------------------------------------------------------------------
# System prompt — Russian fleet operator context
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """
Ты — аналитик данных для систем управления тяжёлой строительной техникой.
Тебе присылают сырые сообщения от операторов в мессенджере.

ТВОЯ ЗАДАЧА: Извлечь структурированные данные из сообщения.

ВСЕГДА возвращай ТОЛЬКО JSON объект, никакого другого текста.

JSON должен содержать:
{
  "intent": одно из: "shift_start" | "shift_end" | "fuel_log" | "hours_log" |
            "issue_report" | "status_update" | "production_log" |
            "inspection_check" | "parts_request" | "handover_note" | "unknown",
  "entities": {
    "reg_number":    "номер машины если есть, иначе null",
    "fuel_volume":   число литров если топливо, иначе null,
    "hours":         число часов если наработка, иначе null,
    "component":     "компонент машины если проблема (engine/hydraulics/tracks/bucket/...)",
    "symptom":       "симптом если проблема (leak/noise/smoke/no_start/overheat/...)",
    "severity":      "info | warning | high | critical — оценка серьёзности",
    "production_qty": число если упоминается выработка, иначе null,
    "production_unit":"единица выработки (кубов/рейсов/тонн) если есть",
    "notes":         "любые важные детали которые не вошли в другие поля"
  },
  "confidence": число от 0.0 до 1.0 — насколько ты уверен в извлечении,
  "reasoning":  "одно предложение почему ты выбрал этот intent"
}

ПРИМЕРЫ:
Вход: "Залил 50 литров на 101-м"
Выход: {"intent":"fuel_log","entities":{"reg_number":"101","fuel_volume":50},"confidence":0.95,"reasoning":"Явное упоминание топлива и номера машины"}

Вход: "Стук какой-то слева в ходовой"
Выход: {"intent":"issue_report","entities":{"component":"tracks","symptom":"noise","severity":"warning"},"confidence":0.78,"reasoning":"Стук — механический симптом, 'слева в ходовой' указывает компонент"}

Вход: "Начинаю смену"
Выход: {"intent":"shift_start","entities":{},"confidence":0.97,"reasoning":"Прямое объявление начала смены"}
""".strip()


# ---------------------------------------------------------------------------
# Provider adapters
# ---------------------------------------------------------------------------

async def _call_anthropic(text: str, session: aiohttp.ClientSession) -> str:
    payload = {
        "model":      LLM_MODEL,
        "max_tokens": 512,
        "system":     SYSTEM_PROMPT,
        "messages":   [{"role": "user", "content": text}],
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


async def _call_yandex(text: str, session: aiohttp.ClientSession) -> str:
    """YandexGPT via Yandex Cloud API."""
    folder_id = os.getenv("YANDEX_FOLDER_ID", "")
    payload = {
        "modelUri": f"gpt://{folder_id}/yandexgpt-lite",
        "completionOptions": {"temperature": 0.1, "maxTokens": 512},
        "messages": [
            {"role": "system", "text": SYSTEM_PROMPT},
            {"role": "user",   "text": text},
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


async def _call_ollama(text: str, session: aiohttp.ClientSession) -> str:
    """Local Ollama / vLLM (OpenAI-compatible)."""
    payload = {
        "model":  LLM_MODEL,
        "stream": False,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": text},
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


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

async def llm_extract(text: str) -> Dict[str, Any]:
    """
    Call the configured LLM to extract structured data from a Russian
    fleet operator message.

    Returns a dict with keys: intent, entities, confidence, reasoning.
    On any failure returns a safe fallback with confidence=0.0 so the
    EventProcessor treats it as unresolved and asks for clarification.
    """
    if not LLM_API_KEY and LLM_PROVIDER != "ollama":
        logger.warning("LLM_API_KEY not set — skipping LLM fallback")
        return _fallback_response(text, "LLM_API_KEY not configured")

    try:
        async with aiohttp.ClientSession() as session:
            if LLM_PROVIDER == "yandex":
                raw = await _call_yandex(text, session)
            elif LLM_PROVIDER == "ollama":
                raw = await _call_ollama(text, session)
            else:
                raw = await _call_anthropic(text, session)

        # Strip markdown fences if model wrapped the JSON
        clean = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        result = json.loads(clean)

        # Ensure required keys exist
        result.setdefault("intent",     "unknown")
        result.setdefault("entities",   {})
        result.setdefault("confidence", 0.5)
        result.setdefault("reasoning",  "")

        logger.info(
            f"LLM fallback result (confidence={result['confidence']:.2f}): "
            f"intent={result['intent']} entities={result['entities']}"
        )
        return result

    except json.JSONDecodeError as e:
        logger.error(f"LLM returned non-JSON: {e} — raw: {raw[:200]}")
        return _fallback_response(text, f"JSON parse error: {e}")
    except aiohttp.ClientError as e:
        logger.error(f"LLM HTTP error: {e}")
        return _fallback_response(text, f"HTTP error: {e}")
    except Exception as e:
        logger.error(f"LLM fallback failed: {e}")
        return _fallback_response(text, str(e))


def _fallback_response(text: str, reason: str) -> Dict[str, Any]:
    return {
        "intent":     "unknown",
        "entities":   {},
        "confidence": 0.0,
        "reasoning":  f"LLM failed: {reason}",
        "error":      reason,
    }
