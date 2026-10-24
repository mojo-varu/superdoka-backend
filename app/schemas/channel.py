"""
app/schemas/channel.py

SPEC-001-R03, SPEC-014: the channel-neutral contract between any messenger
adapter (Telegram today, MAX later) and the engine.

Deliberately NOT under app/channels/ — tests/channels/test_import_boundary.py
caught that engine_entrypoint.py importing app/channels/base.py (where WP-A
originally put these types) violates ADR-0020's literal "the engine must
never import app/channels" rule, even though that same ADR also says the
engine's handle_inbound() signature IS these types. Moving the real
definitions here resolves both halves at once: the engine imports this
module directly (not under app/channels), and app/channels/base.py
re-exports from here so existing "app/channels may import only base.py"
code is unaffected. See the final report for this as a found-and-fixed
issue, not a design intended from the start.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional, Protocol


class ChatType(str, Enum):
    PRIVATE = "private"
    GROUP = "group"
    SUPERGROUP = "supergroup"
    CHANNEL = "channel"


class MediaKind(str, Enum):
    NONE = "none"
    VOICE = "voice"
    PHOTO = "photo"
    OTHER = "other"


@dataclass(frozen=True)
class NormalisedInbound:
    """
    One inbound update, already stripped of any channel-specific shape.
    SPEC-001-R03.
    """
    channel: str                 # "telegram" | "max" | "rest"
    update_id: str                # channel's own update/delivery id — used for the (channel, update_id) dedup key
    chat_id: str
    user_id: str                  # the sender's platform user id (equals chat_id for Telegram private chats)
    message_id: Optional[str]
    timestamp: datetime
    chat_type: ChatType
    text: Optional[str] = None
    media_kind: MediaKind = MediaKind.NONE
    media_file_unique_id: Optional[str] = None
    command: Optional[str] = None         # e.g. "/start", parsed by the adapter
    command_args: Optional[str] = None    # e.g. the invite token after /start
    callback_data: Optional[str] = None   # set instead of text for a callback_query update
    raw: dict[str, Any] = field(default_factory=dict)  # original payload, for debugging only — never logged at INFO


@dataclass(frozen=True)
class InlineButton:
    text: str
    callback_data: str


@dataclass(frozen=True)
class OutboundMessage:
    """
    A reply the engine wants delivered. The engine never sends this itself —
    it only returns a list of these from handle_inbound() (ADR-0020).
    """
    chat_id: str
    text: str
    buttons: Optional[list[list[InlineButton]]] = None   # rows of inline buttons
    callback_answer_text: Optional[str] = None            # if this reply is answering a callback_query


class ChannelAdapter(Protocol):
    """
    Structural contract a concrete channel module satisfies. Not inherited —
    app/channels/telegram/* provides these as plain functions/classes; this
    Protocol exists so the engine's test suite can type-check against it
    without importing aiogram.
    """

    async def parse_inbound(self, raw_update: dict[str, Any]) -> Optional[NormalisedInbound]:
        """Return None for an update type the adapter does not handle (e.g. edited_message)."""
        ...

    async def send_outbound(self, message: OutboundMessage) -> None:
        ...

    async def download_media(self, file_unique_id: str) -> Optional[bytes]:
        ...
