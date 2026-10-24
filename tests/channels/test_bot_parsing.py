"""
tests/channels/test_bot_parsing.py

Covers AC-014-xx fixture shapes for parse_inbound() — pure function, no
aiogram/DB needed, so this is one of the few test files in this phase
CONFIRMED-RUN directly in this sandbox (see the runner at the bottom and
the final report for the exact command/output).
"""
from __future__ import annotations

from app.channels.base import ChatType, MediaKind
from app.channels.telegram.bot import parse_inbound
from tests.channels.fixtures.telegram_updates import (
    BASE_PRIVATE_TEXT_UPDATE,
    CALLBACK_CONFIRM_UPDATE,
    EDITED_MESSAGE_UPDATE,
    GROUP_MESSAGE_UPDATE,
    PHOTO_UPDATE,
    START_NO_PAYLOAD_UPDATE,
    START_WITH_TOKEN_UPDATE,
    VOICE_UPDATE,
)


def test_private_text_parses():
    inbound = parse_inbound(BASE_PRIVATE_TEXT_UPDATE)
    assert inbound is not None
    assert inbound.chat_type == ChatType.PRIVATE
    assert inbound.text == "залил 50 литров"
    assert inbound.chat_id == "555000111"
    assert inbound.user_id == "555000111"
    assert inbound.update_id == "100001"


def test_start_with_token_parses_command_and_args():
    inbound = parse_inbound(START_WITH_TOKEN_UPDATE)
    assert inbound.command == "/start"
    assert inbound.command_args == "abc123invitetoken"


def test_start_without_payload_has_no_args():
    inbound = parse_inbound(START_NO_PAYLOAD_UPDATE)
    assert inbound.command == "/start"
    assert inbound.command_args is None


def test_group_message_parses_as_group_chat_type():
    inbound = parse_inbound(GROUP_MESSAGE_UPDATE)
    assert inbound.chat_type == ChatType.GROUP


def test_voice_message_sets_media_kind_and_file_id():
    inbound = parse_inbound(VOICE_UPDATE)
    assert inbound.media_kind == MediaKind.VOICE
    assert inbound.media_file_unique_id == "AgAD_voice_1"


def test_photo_message_sets_media_kind():
    inbound = parse_inbound(PHOTO_UPDATE)
    assert inbound.media_kind == MediaKind.PHOTO
    assert inbound.media_file_unique_id == "AgAD_photo_1"


def test_callback_query_parses_data_not_text():
    inbound = parse_inbound(CALLBACK_CONFIRM_UPDATE)
    assert inbound.callback_data == "v1:confirm:42"
    assert inbound.text is None
    assert inbound.chat_id == "555000111"


def test_edited_message_returns_none():
    # SPEC-001/WP-D: edited_message is ignored this phase.
    assert parse_inbound(EDITED_MESSAGE_UPDATE) is None


if __name__ == "__main__":
    failures = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                failures += 1
                print(f"FAIL {name}: {e}")
    raise SystemExit(1 if failures else 0)
