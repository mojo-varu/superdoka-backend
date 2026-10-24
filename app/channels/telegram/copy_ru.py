"""
app/channels/telegram/copy_ru.py

SPEC-015-R11: every Russian user-facing string in app/channels lives here.
No Russian string is inlined elsewhere in this package.

OQ-015-1: the consent notice text below is a DRAFT. It MUST be reviewed by
a human and a lawyer before pilot (SPEC-015-R03, SPEC-016 §2 non-goals).
Do not treat it as final copy.
"""
from __future__ import annotations

CONSENT_TEXT_VERSION = "v1-draft"

WELCOME_AFTER_BIND = (
    "Добро пожаловать! Пишите как обычному мастеру — я записываю топливо, "
    "часы и проблемы. Если что-то не так, просто поправьте следующим "
    "сообщением."
)

INVALID_OR_EXPIRED_INVITE = (
    "Ссылка недействительна или уже использована. Запросите новую ссылку у "
    "владельца."
)

ALREADY_BOUND_ELSEWHERE = (
    "Этот аккаунт уже привязан в системе. Если это ошибка, напишите "
    "владельцу."
)

ONBOARDING_UNBOUND = (
    "Вас пока нет в системе. Попросите владельца отправить вам ссылку для "
    "регистрации (команда /start со ссылкой)."
)

GROUP_CHAT_NOT_SUPPORTED = (
    "Я работаю только в личных сообщениях. Напишите мне напрямую, пожалуйста."
)

HELP_TEXT = (
    "Просто пишите, что происходит на смене — залили топливо, сколько "
    "часов наработки, есть ли проблемы. Я отвечу коротким подтверждением "
    "или уточню один вопрос, если что-то не понял."
)

# --- Consent (DRAFT — OQ-015-1, legal review required before pilot) --------
CONSENT_NOTICE = (
    "Прежде чем продолжить: сообщения, которые вы отправляете боту, "
    "сохраняются для учёта смен и могут быть переданы владельцу техники. "
    "Нажмите «Согласен», чтобы продолжить."
)
CONSENT_BUTTON_TEXT = "Согласен ✓"
CONSENT_RECORDED = "Спасибо! Теперь можно писать как обычно."

# --- Confirmation flow (SPEC-015-R04/R06/R07) -------------------------------
CONFIRM_BUTTON_TEXT = "Верно ✓"
CORRECT_BUTTON_TEXT = "Исправить ✏️"

ALREADY_RECORDED = "Уже записано ✓"
STALE_CALLBACK = "Это предложение больше не действует."

AWAITING_CORRECTION_PROMPT = "Хорошо, напишите правильное значение."
CORRECTION_APPLIED = "Исправлено ✓"
CORRECTION_FAILED_STALE = (
    "Не получилось применить исправление — похоже, запись уже устарела. "
    "Напишите заново, если нужно."
)
CORRECTION_NO_FIELD_FOUND = (
    "Не разобрал новое значение. Напишите, например: «50 литров» или «6 часов»."
)

# --- Media (SPEC-015-R09/R10) ------------------------------------------------
VOICE_NOT_SUPPORTED = (
    "Голосовые сообщения пока не поддерживаются — напишите, пожалуйста, "
    "текстом."
)
MEDIA_NOT_SUPPORTED = "Пока понимаю только текст. Напишите, пожалуйста, словами."

# --- Errors (SPEC-015-R12 — never expose internals) -------------------------
GENERIC_ERROR = "Что-то пошло не так. Попробуйте ещё раз немного позже."
UNKNOWN_COMMAND = "Не знаю такую команду. Напишите /help."

# --- Flood limit (SPEC-016-R02) ---------------------------------------------
FLOOD_LIMITED = "Слишком много сообщений подряд — подождите минуту."


def confirm_fuel(volume: float) -> str:
    return f"Принял, {volume:g} литров топлива. Всё верно?"


def confirm_hours(hours: float) -> str:
    return f"Принял, {hours:g} часов наработки. Всё верно?"


def confirm_issue(description: str) -> str:
    trimmed = description[:80] + ("…" if len(description) > 80 else "")
    return f"Записываю проблему: {trimmed}. Всё верно?"


def confirm_generic(event_type: str) -> str:
    return "Записал. Всё верно?"
