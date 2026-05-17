"""
app/core/persona.py
====================
Loads the VFM persona document once at startup and provides
it to the agency layer.

The persona is loaded from VFM_PERSONA.md which lives alongside
this file. If the file is absent, a minimal fallback is used.

The full persona is injected into T3-T8 prompts where the LLM
needs to reason. T1 and T2 are template-driven and do not need it.
"""

import logging
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

_PERSONA_PATH = Path(__file__).parent / "VFM_PERSONA.md"

_MINIMAL_FALLBACK = """
Ты — VFM, цифровой прораб. Управляешь флотом тяжёлой техники от имени
владельца. Работаешь как опытный Fleet Manager: знаешь каждую машину,
замечаешь отклонения, докладываешь владельцу только то, что важно.

С операторами: коротко, конкретно, по-деловому. Максимум 3 предложения.
С владельцем: сначала ситуация, потом детали. Только аномалии и решения.

Никогда не спрашивай то, что уже знаешь из контекста.
Никогда не отправляй два вопроса в одном сообщении.
Никогда не звучи как робот или форма — звучи как коллега.
""".strip()


@lru_cache(maxsize=1)
def load_persona() -> str:
    """
    Load the VFM persona document. Cached after first call.
    Returns the full markdown content.
    """
    if _PERSONA_PATH.exists():
        content = _PERSONA_PATH.read_text(encoding="utf-8")
        logger.info(f"VFM persona loaded from {_PERSONA_PATH} "
                    f"({len(content.split())} words)")
        return content
    else:
        logger.warning(
            f"VFM_PERSONA.md not found at {_PERSONA_PATH} — "
            f"using minimal fallback"
        )
        return _MINIMAL_FALLBACK


def get_persona_summary() -> str:
    """
    Returns a compact (~200 token) summary of the persona for injection
    into prompts where the full document would be too long.
    Used for T1/T2 template confirmations that still need voice guidance.
    """
    return (
        "Ты — VFM, цифровой прораб флота тяжёлой техники. "
        "СТРОГИЕ ПРАВИЛА: "
        "1) Отвечай ТОЛЬКО на русском языке — никаких английских или китайских слов. "
        "2) Максимум 2 предложения в ответе. "
        "3) Один вопрос за раз — не больше. "
        "4) Всегда используй имя машины из контекста. "
        "5) Звучи как коллега, не как система. "
        "6) Для офф-топик сообщений: одно предложение — признай, одно — спроси о машине."
    )
