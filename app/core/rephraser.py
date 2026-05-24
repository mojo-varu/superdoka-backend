"""
app/core/rephraser.py

Rephrasing layer — sits between template filling and response delivery.

Design principles:
- Each T-route has a semantic frame that tells the model what register to stay in
- The model receives: frame + filled template. Nothing else.
- No context graph. No persona file. No shift state.
- Validator checks facts (numbers + entities) and register (no invented alerts)
- On any failure the original filled template is returned silently
- T8 is never rephrased — urgency must not be softened
"""
from __future__ import annotations

import logging
import os
import re

import aiohttp

logger = logging.getLogger(__name__)

_LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:11434")
_LLM_MODEL    = os.getenv("LLM_MODEL", "qwen2.5:3b-instruct")

# ── Semantic frames per route ─────────────────────────────────────────────────
# Each frame tells the model exactly what kind of message it is rephrasing.
# This prevents register drift — the model cannot turn a confirmation into a warning.

ROUTE_FRAMES: dict[str, str] = {
    "T1": (
        "Подтверждение начала смены. "
        "Оператор ждёт сигнала что система его зафиксировала и можно работать. "
        "Тон: короткий, бодрый. Уместно пожелание удачи."
    ),
    "T1_END": (
        "Подтверждение завершения смены. "
        "Оператор закончил работу и ждёт финального подтверждения. "
        "Тон: спокойный, деловой, финальный. "
        "Неуместно: пожелания удачи, призывы продолжать работу."
    ),
    "T2": (
        "Подтверждение что конкретные данные записаны — топливо, часы или проблема. "
        "Оператор ждёт подтверждения с точной цифрой. "
        "Тон: деловой, нейтральный, сухой. "
        "Обязательно: цифра из оригинала должна быть в ответе. "
        "Строго запрещено: слова 'удачи', 'удача', 'успех', пожелания любого рода, предупреждения, вопросы."
    ),
    "T3": (
        "Уточняющий вопрос — не хватает одного поля для записи. "
        "Оператор не указал машину, объём или описание. "
        "Тон: дружелюбный, прямой. Ровно один вопрос."
    ),
    "T4": (
        "Оффтопик принят, мягкое возвращение к машине. "
        "Оператор написал что-то не операционное. "
        "Тон: понимающий, лёгкий. "
        "Неуместно: игнорировать сообщение, быть резким."
    ),
    "T5": (
        "Вопрос об аномальном расходе топлива. "
        "Система заметила расход выше нормы и уточняет причину. "
        "Тон: спокойный, один вопрос. "
        "Неуместно: паника, обвинения, инструкции."
    ),
    "T6": (
        "Наблюдение повторяющегося паттерна — информация для оператора. "
        "Тон: нейтральный, информационный. "
        "Неуместно: тревога, инструкции, вопросы."
    ),
    "T7": (
        "Итог смены — краткая сводка фактов. "
        "Тон: деловой, финальный. "
        "Обязательно: все цифры из оригинала. "
        "Неуместно: оценки, пожелания, вопросы."
    ),
    # T8 is never rephrased — handled by the exclusion check in rephrase_safe
}

_DEFAULT_FRAME = (
    "Системное сообщение оператору тяжёлой техники. "
    "Тон: нейтральный, деловой. "
    "Неуместно: новые факты, предупреждения, вопросы."
)

# ── Fact extraction ───────────────────────────────────────────────────────────

def _extract_numbers(text: str) -> set[str]:
    return set(re.findall(r'\d+(?:[.,]\d+)?', text))


def _extract_entities(text: str) -> set[str]:
    return set(re.findall(
        r'[А-ЯA-Z]\d{3}[А-ЯA-Z]{2}\d{2,3}'  # reg plates: А771МР77
        r'|[А-ЯЁ][а-яё]+-\d+',               # aliases: Экскаватор-1
        text, re.UNICODE,
    ))

# ── Language check ────────────────────────────────────────────────────────────

def _is_russian(text: str) -> bool:
    non_russian = re.sub(r'[А-ЯЁа-яё0-9\s.,!?:;—–\-«»"\'✓%()/]', '', text)
    return len(non_russian) <= 3

# ── Core validator ────────────────────────────────────────────────────────────

def validate_rephrase(original: str, rephrased: str) -> tuple[bool, str]:
    """
    Returns (is_valid, rejection_reason).
    Checks language, facts (numbers + entities), and length sanity.
    The semantic frame prevents register drift at the source — the validator
    only needs to catch factual loss and non-Russian output.
    """
    if not _is_russian(rephrased):
        return False, "non_russian_content"

    if len(rephrased) > len(original) * 3:
        return False, "excessive_length"

    missing_numbers  = _extract_numbers(original)  - _extract_numbers(rephrased)
    missing_entities = _extract_entities(original) - _extract_entities(rephrased)

    if missing_numbers:
        return False, f"missing_numbers:{missing_numbers}"
    if missing_entities:
        return False, f"missing_entities:{missing_entities}"

    return True, "ok"

# ── Prompt builder ───────────────────────────────────────────────────────────

def _build_prompt(filled_template: str, task_type: str | None = None) -> str:
    frame = ROUTE_FRAMES.get(task_type or "", _DEFAULT_FRAME)
    return f"""# ROLE
Ты — цифровой супервайзер тяжёлой техники. Ты общаешься с машинистами на стройке или в карьере. Твои сообщения короткие, точные, человеческие.

# CONTEXT
Тип сообщения: {frame}

# CONSTRAINTS
- Отвечай ТОЛЬКО на русском языке
- Все цифры должны остаться точно такими же как в оригинале
- Все названия машин должны остаться точно такими же как в оригинале
- Не добавляй факты которых нет в оригинале
- Не убирай факты которые есть в оригинале
- Максимум два предложения
- Не повторяй слова из раздела TASK

# TASK
Перефразируй следующее сообщение естественным языком в соответствии с CONTEXT и CONSTRAINTS.

Оригинал: {filled_template}

# OUTPUT
Переписанное (только текст, без пояснений):"""


# ── LLM call ─────────────────────────────────────────────────────────────────

async def rephrase(
    filled_template: str,
    task_type: str | None = None,
) -> str:
    """
    Calls Ollama with the structured prompt for this route.
    Returns rephrased text or raises on failure.
    Caller must handle exceptions.
    """
    prompt = _build_prompt(filled_template, task_type)

    payload = {
        "model":    _LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream":   False,
        "options":  {
            "num_predict":    80,
            "temperature":    0.45,
            "repeat_penalty": 1.15,
            "stop":           ["\n\n", "###", "Оригинал:"],
        },
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{_LLM_BASE_URL}/api/chat",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=45),
        ) as resp:
            data = await resp.json()
            raw = data["message"]["content"].strip()
            raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()
            # Strip the "Переписанное:" prefix if the model echoes it
            raw = re.sub(r'^[Пп]ереписанное\s*:\s*', '', raw).strip()
            return raw

# ── Safe wrapper ──────────────────────────────────────────────────────────────

async def rephrase_safe(
    filled_template: str,
    task_type: str | None = None,
) -> tuple[str, bool]:
    """
    Returns (reply_text, was_rephrased).
    Always returns a valid reply — never raises.
    On any failure returns the original filled_template unchanged.
    """
    if task_type == "T8":
        return filled_template, False

    if not filled_template or not filled_template.strip():
        return filled_template, False

    try:
        rephrased = await rephrase(filled_template, task_type)
        is_valid, reason = validate_rephrase(filled_template, rephrased)

        if is_valid:
            logger.info(f"[rephraser] {task_type} → rephrased successfully")
            return rephrased, True
        else:
            logger.info(f"[rephraser] {task_type} → validator rejected ({reason}), using original")
            return filled_template, False

    except Exception as e:
        logger.warning(f"[rephraser] {task_type} → exception: {e}, using original")
        return filled_template, False
