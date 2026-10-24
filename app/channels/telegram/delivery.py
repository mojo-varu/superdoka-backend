"""
app/channels/telegram/delivery.py

WP-F / SPEC-014-R08–R12: one send wrapper. Splits long text at paragraph
boundaries, avoids parse_mode injection, retries on retry_after up to a cap,
marks "blocked by user" as unreachable, and times out independently of the
overall pipeline.

OQ-014-1: the exact Telegram message-length limit and retry_after semantics
are NOT hardcoded from training data — MESSAGE_LIMIT below is a
conservative placeholder explicitly marked for verification against the
current Bot API docs before this ships (the build prompt's own instruction;
this fork's sandbox has no network access to check live, see the final
report). Re-verify before relying on it.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Optional

from app.channels.base import OutboundMessage

logger = logging.getLogger(__name__)

# OQ-014-1 — placeholder, MUST be re-verified against current Bot API docs.
MESSAGE_LIMIT = 4096
RETRY_CAP = 3
OUTBOUND_TIMEOUT_SECONDS = 10   # SPEC-014-R12: shorter than the overall pipeline timeout


class UserUnreachable(Exception):
    """Raised internally to signal a 'blocked by user' style error — callers
    (app/channels/worker.py) catch this and mark the user unreachable
    (User.is_reachable=False) rather than retrying or crashing."""


def split_text(text: str, limit: int = MESSAGE_LIMIT) -> list[str]:
    """Splits at paragraph boundaries (\n\n) first, falling back to hard
    slicing only if a single paragraph alone exceeds the limit."""
    if len(text) <= limit:
        return [text]

    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
        if len(para) <= limit:
            current = para
        else:
            for i in range(0, len(para), limit):
                chunks.append(para[i:i + limit])
            current = ""
    if current:
        chunks.append(current)
    return chunks or [text[:limit]]


def escape_plain(text: str) -> str:
    """
    SPEC-014-R09: default to a parse_mode that cannot be used for injection.
    We send plain text (no parse_mode at all) for every operator/LLM-sourced
    string, which makes escaping moot for Telegram's own formatting — this
    function exists as the single place that decision is enforced, so a
    future switch to MarkdownV2/HTML has one call site to update with real
    escaping rather than relying on every call site remembering to.
    """
    return text


async def send_with_resilience(
    bot_send_fn: Callable[..., Any],
    chat_id: str,
    text: str,
    reply_markup: Optional[Any] = None,
) -> None:
    """
    bot_send_fn is the raw aiogram `bot.send_message` (or compatible) call.
    Injected rather than imported directly so this module has no aiogram
    import at module scope beyond the type hint's Any — keeps this testable
    with a fake Bot API (SPEC-018) without a real aiogram Bot instance.
    """
    chunks = split_text(escape_plain(text))
    for i, chunk in enumerate(chunks):
        markup = reply_markup if i == len(chunks) - 1 else None
        await _send_one_with_retry(bot_send_fn, chat_id, chunk, markup)


async def _send_one_with_retry(
    bot_send_fn: Callable[..., Any],
    chat_id: str,
    text: str,
    reply_markup: Optional[Any],
) -> None:
    attempt = 0
    while True:
        attempt += 1
        try:
            await asyncio.wait_for(
                bot_send_fn(chat_id=chat_id, text=text, reply_markup=reply_markup),
                timeout=OUTBOUND_TIMEOUT_SECONDS,
            )
            return
        except asyncio.TimeoutError:
            logger.warning("Outbound send to chat %s timed out (attempt %d)", chat_id, attempt)
            if attempt >= RETRY_CAP:
                return   # SPEC-014-R10: drop rather than block the worker
        except Exception as e:
            retry_after = _extract_retry_after(e)
            is_blocked = _is_blocked_by_user_error(e)

            if is_blocked:
                raise UserUnreachable(str(e)) from e

            if retry_after is not None and attempt < RETRY_CAP:
                logger.info("Rate limited sending to chat %s, retry_after=%ss (attempt %d)", chat_id, retry_after, attempt)
                await asyncio.sleep(min(retry_after, 30))
                continue

            logger.error("Outbound send to chat %s failed permanently: %s", chat_id, e)
            return   # drop the single message rather than crash the worker (SPEC-014-R10)


def _extract_retry_after(exc: Exception) -> Optional[float]:
    """aiogram raises TelegramRetryAfter with a .retry_after attribute on
    429 responses. Duck-typed here (no aiogram import at module scope) so
    this is testable with a plain fake exception in SPEC-018's fake Bot API."""
    return getattr(exc, "retry_after", None)


def _is_blocked_by_user_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "bot was blocked" in message or "chat not found" in message or "user is deactivated" in message
