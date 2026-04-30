"""
app/core/model_profiles.py

Per-model prompt patches and Ollama call tuning.

Why this exists
───────────────
Different open-source models need slightly different prompt enforcement.
Qwen2.5 and Qwen3 are excellent JSON producers at temperature=0, but they
have two well-known quirks we need to guard against:

  1. Preamble leak — on ambiguous inputs they occasionally emit one sentence
     of reasoning before the JSON brace.  The prompt already says "первый
     символ должен быть '{'", but we add a second line that's phrased as
     a constraint rather than a description, which lands better in the
     Qwen chat template.

  2. Русские числа-слова — "двести литров" → fuel_volume: "двести" instead
     of 200.  The coercion layer in context_llm.py catches this via regex,
     but adding an explicit example to the ЗАПРЕЩЕНО block reduces the
     incidence significantly.

Usage
─────
Call `patch_forbidden_block(base_text, model_name)` to get the right
ЗАПРЕЩЕНО section for the configured model.  context_prompt.py calls this.

Call `ollama_options(model_name)` to get the right sampling options dict
to pass in the Ollama API payload.
"""

from __future__ import annotations
import os

_MODEL = os.getenv("LLM_MODEL", "qwen2.5:7b-instruct").lower()


# ---------------------------------------------------------------------------
# ЗАПРЕЩЕНО section text, base + model-specific additions
# ---------------------------------------------------------------------------

_BASE_FORBIDDEN = (
    "- НЕ изобретай числа: если fuel_volume не упомянут — верни null, не угадывай.\n"
    "- НЕ угадывай номер машины: если оператор не написал номер явно — верни null.\n"
    "- НЕ интерпретируй «проблем нет» как issue_report — это status_update.\n"
    "- НЕ добавляй текст вне JSON: первый символ ответа должен быть '{', последний '}'.\n"
    "- НЕ используй ```json фенсинг — только сырой JSON."
)

# Extra lines for Qwen2.5 / Qwen3 (both use qwen chat template)
_QWEN_EXTRA = (
    "\n- ОБЯЗАТЕЛЬНО: твой ответ начинается РОВНО с символа '{'. "
    "Никакого вступления, никаких слов до JSON.\n"
    "- Числа ВСЕГДА цифрами: «двести» → 200, «пять» → 5, «восемь с половиной» → 8.5."
)

# Llama-family models don't need the extra lines — they follow JSON schema well
_LLAMA_EXTRA = ""


def patch_forbidden_block(model: str | None = None) -> str:
    """
    Return the full ЗАПРЕЩЕНО block text for the given model name.
    Falls back to the base block if the model is unrecognised.
    """
    m = (model or _MODEL).lower()
    if "qwen" in m:
        return _BASE_FORBIDDEN + _QWEN_EXTRA
    return _BASE_FORBIDDEN


# ---------------------------------------------------------------------------
# Ollama sampling options
# ---------------------------------------------------------------------------

def ollama_options(model: str | None = None) -> dict:
    """
    Returns the `options` dict for the Ollama /v1/chat/completions payload.

    Qwen2.5 / Qwen3 specifics
    ─────────────────────────
    temperature=0   — fully deterministic; extraction is not a creative task.
    repeat_penalty  — Qwen models occasionally repeat JSON keys on long
                      contexts.  A mild penalty (1.05) stops this without
                      affecting the short outputs we generate.
    num_predict     — cap output at 600 tokens.  Our JSON responses are
                      < 200 tokens; this is a safety ceiling.
    top_k=1         — greedy decoding.  Combined with temperature=0 this
                      guarantees the same output for the same input.
    """
    m = (model or _MODEL).lower()
    base = {
        "temperature":    0.0,
        "num_predict":    600,
    }
    if "qwen" in m:
        base.update({
            "repeat_penalty": 1.05,
            "top_k":          1,
        })
    return base
