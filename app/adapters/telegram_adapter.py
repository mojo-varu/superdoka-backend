"""
app/adapters/telegram_adapter.py

Replaces the direct CRUD calls in your existing Telegram bot handler.

BEFORE (existing pattern in groups.py):
    @router.post("/messages")
    async def receive_message(payload, db):
        msg = GroupMessage(**payload)
        db.add(msg)
        await db.commit()
        ner_result = NERHandler().extract(msg.message_text)
        # saves to fuel_logs directly, no context, no rules

AFTER (this adapter):
    All messages flow through process_telegram_message() which calls
    EventProcessor and gets back a FleetUpdate with reply_text + actions.

Integration: replace the body of your existing /groups/messages endpoint
with a single call to process_telegram_message(). Zero route changes needed.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.fleet_update import FleetUpdate, MessageSource, Modality
from app.services.event_processor import event_processor

logger = logging.getLogger(__name__)


async def process_telegram_message(
    db:               AsyncSession,
    telegram_user_id: int,
    chat_id:          int,
    text:             str,
    message_id:       Optional[int] = None,
    voice_file_id:    Optional[str] = None,
    photo_file_id:    Optional[str] = None,
    send_message_fn:  Optional[Callable] = None,
) -> FleetUpdate:
    """
    Single entry point for all inbound Telegram messages.

    Steps:
      1. Build FleetUpdate from raw Telegram fields
      2. Run EventProcessor (NER → session → rules → actions)
      3. Send reply via send_message_fn if provided
      4. Return processed FleetUpdate

    Usage in your existing groups.py:
        from app.adapters.telegram_adapter import process_telegram_message

        @router.post("/messages")
        async def receive_group_message(payload: GroupMessageIn, db=Depends(get_db)):
            result = await process_telegram_message(
                db               = db,
                telegram_user_id = payload.telegram_user_id,
                chat_id          = payload.chat_id,
                text             = payload.message_text,
                message_id       = payload.telegram_message_id,
                send_message_fn  = bot.send_message,   # your aiogram/pyTelegramBotAPI bot
            )
            return {"reply": result.reply_text, "intent": result.intent}
    """
    modality  = Modality.TEXT
    media_url = None

    if voice_file_id:
        modality  = Modality.VOICE
        media_url = voice_file_id
    elif photo_file_id:
        modality  = Modality.IMAGE
        media_url = photo_file_id

    update = FleetUpdate.from_raw(
        source         = MessageSource.TELEGRAM,
        operator_id    = str(telegram_user_id),
        chat_id        = str(chat_id),
        raw_text       = text or "",
        modality       = modality,
        media_url      = media_url,
        message_id     = str(message_id) if message_id else None,
    )

    processed = await event_processor.process(db, update)

    if send_message_fn and processed.reply_text:
        markup = _confirmation_keyboard(processed) if processed.needs_confirmation else None
        try:
            await send_message_fn(
                chat_id      = chat_id,
                text         = processed.reply_text,
                reply_markup = markup,
            )
        except Exception as e:
            logger.error(f"Failed to send reply to chat {chat_id}: {e}")

    return processed


def _confirmation_keyboard(update: FleetUpdate) -> Dict[str, Any]:
    """Telegram inline keyboard for the operator confirmation flow."""
    event_id = update.timeline_event_id or 0
    return {
        "inline_keyboard": [[
            {"text": "Верно ✓",     "callback_data": f"confirm:{event_id}"},
            {"text": "Исправить ✗", "callback_data": f"correct:{event_id}"},
        ]]
    }


async def handle_callback_query(
    db:              AsyncSession,
    data:            str,     # "confirm:42" or "correct:42"
    chat_id:         int,
    send_message_fn: Optional[Callable] = None,
) -> None:
    """
    Handles inline keyboard callbacks from the confirmation flow.

    Wire to your bot's callback handler:
        @bot.callback_query_handler(func=lambda c: True)
        async def on_callback(call):
            await handle_callback_query(
                db=db, data=call.data,
                chat_id=call.message.chat.id,
                send_message_fn=bot.send_message,
            )
    """
    if not data or ":" not in data:
        return

    action, event_id_str = data.split(":", 1)

    if action == "confirm":
        reply = "Отлично, всё записано ✓"

    elif action == "correct":
        reply = (
            "Хорошо, отправьте исправленное сообщение.\n"
            "Например: «Залил 55 литров» или «Наработка 9 часов»"
        )

    else:
        return

    if send_message_fn and reply:
        try:
            await send_message_fn(chat_id=chat_id, text=reply)
        except Exception as e:
            logger.error(f"Callback reply failed: {e}")
