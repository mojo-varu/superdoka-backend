"""
tests/channels/fixtures/telegram_updates.py

Raw Telegram update JSON shapes, matching the Bot API's documented public
format (not aiogram's wrapper — see app/channels/telegram/bot.py's
docstring for why parse_inbound works on raw dicts). Used across the
channel test files.
"""
from __future__ import annotations

BASE_PRIVATE_TEXT_UPDATE = {
    "update_id": 100001,
    "message": {
        "message_id": 501,
        "date": 1761000000,
        "chat": {"id": 555000111, "type": "private", "first_name": "Иван"},
        "from": {"id": 555000111, "first_name": "Иван", "is_bot": False},
        "text": "залил 50 литров",
    },
}

START_WITH_TOKEN_UPDATE = {
    "update_id": 100002,
    "message": {
        "message_id": 502,
        "date": 1761000001,
        "chat": {"id": 555000111, "type": "private", "first_name": "Иван"},
        "from": {"id": 555000111, "first_name": "Иван", "is_bot": False},
        "text": "/start abc123invitetoken",
    },
}

START_NO_PAYLOAD_UPDATE = {
    "update_id": 100003,
    "message": {
        "message_id": 503,
        "date": 1761000002,
        "chat": {"id": 555000222, "type": "private", "first_name": "Пётр"},
        "from": {"id": 555000222, "first_name": "Пётр", "is_bot": False},
        "text": "/start",
    },
}

GROUP_MESSAGE_UPDATE = {
    "update_id": 100004,
    "message": {
        "message_id": 504,
        "date": 1761000003,
        "chat": {"id": -100555, "type": "group", "title": "Бригада"},
        "from": {"id": 555000333, "first_name": "Операторы", "is_bot": False},
        "text": "привет всем",
    },
}

VOICE_UPDATE = {
    "update_id": 100005,
    "message": {
        "message_id": 505,
        "date": 1761000004,
        "chat": {"id": 555000111, "type": "private", "first_name": "Иван"},
        "from": {"id": 555000111, "first_name": "Иван", "is_bot": False},
        "voice": {"file_id": "AWACAgIAAx", "file_unique_id": "AgAD_voice_1", "duration": 4},
    },
}

PHOTO_UPDATE = {
    "update_id": 100006,
    "message": {
        "message_id": 506,
        "date": 1761000005,
        "chat": {"id": 555000111, "type": "private", "first_name": "Иван"},
        "from": {"id": 555000111, "first_name": "Иван", "is_bot": False},
        "photo": [{"file_id": "p1", "file_unique_id": "AgAD_photo_1", "width": 90, "height": 90}],
    },
}

CALLBACK_CONFIRM_UPDATE = {
    "update_id": 100007,
    "callback_query": {
        "id": "cbq1",
        "from": {"id": 555000111, "first_name": "Иван", "is_bot": False},
        "message": {
            "message_id": 507,
            "chat": {"id": 555000111, "type": "private"},
        },
        "data": "v1:confirm:42",
    },
}

EDITED_MESSAGE_UPDATE = {
    "update_id": 100008,
    "edited_message": {
        "message_id": 501,
        "date": 1761000006,
        "chat": {"id": 555000111, "type": "private"},
        "from": {"id": 555000111, "is_bot": False},
        "text": "залил 55 литров",
    },
}
