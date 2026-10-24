"""
app/channels/telegram/bot.py

Shared Bot client + inbound parsing, used by both webhook.py and polling.py
(SPEC-014-R01: "sharing the same handler code for both").

parse_inbound() works directly on Telegram's raw update JSON (the Bot API's
own stable public shape) rather than through aiogram's typed Update model,
deliberately — this sandbox has no network access to verify aiogram 3's
exact current API surface (see final report), so the only aiogram
dependency kept is the well-established Bot client (send_message,
set_webhook, delete_webhook, get_webhook_info, download) used in
admin.py/delivery.py/polling.py. A human running this for real should still
`pip install aiogram` and smoke-test against the dev bot before trusting it
end to end (not possible in this sandbox either — see report).

NOT part of the ADR-0020 import boundary from the engine side — this file
lives entirely on the app/channels side.
"""
from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Optional

from app.channels.base import ChatType, MediaKind, NormalisedInbound
from app.channels.settings import get_bot_settings

_CHAT_TYPE_MAP = {
    "private": ChatType.PRIVATE,
    "group": ChatType.GROUP,
    "supergroup": ChatType.SUPERGROUP,
    "channel": ChatType.CHANNEL,
}


@lru_cache(maxsize=1)
def get_bot() -> Any:
    """Lazily constructs the aiogram Bot singleton. Import deferred to the
    function body so this module is importable (e.g. by tests exercising
    parse_inbound) without aiogram installed, as long as get_bot() itself
    isn't called."""
    from aiogram import Bot   # local import — see module docstring

    settings = get_bot_settings()
    return Bot(token=settings.bot_token)


def parse_inbound(raw_update: dict) -> Optional[NormalisedInbound]:
    """
    ChannelAdapter.parse_inbound, SPEC-001-R03. Returns None for update
    types we don't handle (edited_message, etc. — logged by the caller).
    Operates on Telegram's raw JSON shape directly (see module docstring).
    """
    update_id = raw_update.get("update_id")
    if update_id is None:
        return None

    if "callback_query" in raw_update:
        return _parse_callback_query(raw_update, update_id)
    if "message" in raw_update:
        return _parse_message(raw_update["message"], update_id)
    # edited_message, channel_post, etc. — not handled this phase (WP-D note).
    return None


def _parse_message(message: dict, update_id: int) -> Optional[NormalisedInbound]:
    chat = message.get("chat", {})
    from_user = message.get("from", {})
    chat_type = _CHAT_TYPE_MAP.get(chat.get("type"), ChatType.PRIVATE)

    text = message.get("text")
    command: Optional[str] = None
    command_args: Optional[str] = None
    if text and text.startswith("/"):
        parts = text.split(maxsplit=1)
        command = parts[0].split("@")[0]   # strip a /start@botname suffix
        command_args = parts[1] if len(parts) > 1 else None

    media_kind = MediaKind.NONE
    media_file_unique_id = None
    if "voice" in message:
        media_kind = MediaKind.VOICE
        media_file_unique_id = message["voice"].get("file_unique_id")
    elif "photo" in message:
        media_kind = MediaKind.PHOTO
        photos = message["photo"]
        media_file_unique_id = photos[-1].get("file_unique_id") if photos else None
    elif any(k in message for k in ("document", "video", "audio", "sticker")):
        media_kind = MediaKind.OTHER

    return NormalisedInbound(
        channel="telegram",
        update_id=str(update_id),
        chat_id=str(chat.get("id")),
        user_id=str(from_user.get("id")),
        message_id=str(message.get("message_id")) if message.get("message_id") is not None else None,
        timestamp=datetime.fromtimestamp(message.get("date", 0), tz=timezone.utc).replace(tzinfo=None),
        chat_type=chat_type,
        text=text,
        media_kind=media_kind,
        media_file_unique_id=media_file_unique_id,
        command=command,
        command_args=command_args,
        raw=message,
    )


def _parse_callback_query(raw_update: dict, update_id: int) -> Optional[NormalisedInbound]:
    cq = raw_update["callback_query"]
    message = cq.get("message", {}) or {}
    chat = message.get("chat", {})
    from_user = cq.get("from", {})

    return NormalisedInbound(
        channel="telegram",
        update_id=str(update_id),
        chat_id=str(chat.get("id") or from_user.get("id")),
        user_id=str(from_user.get("id")),
        message_id=str(message.get("message_id")) if message.get("message_id") is not None else None,
        timestamp=datetime.utcnow(),
        chat_type=_CHAT_TYPE_MAP.get(chat.get("type"), ChatType.PRIVATE),
        callback_data=cq.get("data"),
        raw=raw_update,
    )
