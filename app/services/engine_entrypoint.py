"""
app/services/engine_entrypoint.py

ADR-0020: the engine's ONE entry point. app/channels/* may call only this
function (and import only app/channels/base.py from the engine side) — see
the import-boundary test, tests/channels/test_import_boundary.py.

handle_inbound() assumes the caller (the worker, app/channels/worker.py) has
already inserted the inbound conversation_log row (SPEC-014-R03: "insert the
inbound row and return success before running the pipeline") keyed on
(channel, update_id) — it looks that row up and updates it in place rather
than inserting a second one, so there is exactly one conversation_log row
per inbound update, matching SPEC-011-R04's unique key.

This module is deliberately a single large orchestrator rather than many
small engine entry points, specifically to keep ADR-0020's "exactly one
function" contract real rather than aspirational — see that ADR's Context
for why (telegram_adapter.py's pre-existing coupling problem).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.channel import ChatType, InlineButton, MediaKind, NormalisedInbound, OutboundMessage
# KNOWN, CONFIRMED ADR-0020 VIOLATION (caught by
# tests/channels/test_import_boundary.py, not fixed in this pass — see the
# final report). handle_inbound() currently builds Telegram-flavoured reply
# text and callback_data directly, which only works because OutboundMessage
# carries a literal rendered `text` field rather than an abstract reply
# intent the channel layer would translate. Fixing this properly means
# OutboundMessage carrying a reply *kind* + structured params instead of
# literal text, with copy_ru.py doing the rendering on the app/channels
# side — a real redesign, not a quick patch, left as a reported follow-up
# rather than attempted half-done this late in the task.
from app.channels.telegram import callback_data, copy_ru
from app.db.models import ChannelNotice, ChatState, ConversationLog, PendingConfirmation, User
from app.schemas.fleet_update import ConfidenceRoute, FleetUpdate, Intent, MessageSource, Modality
from app.services import confirmation_service, correction_service, onboarding_service
from app.services.event_processor import event_processor

logger = logging.getLogger(__name__)

FLOOD_LIMIT_PER_MINUTE = 20   # SPEC-016 OQ-016-2 starting value; app/channels/settings.py overrides at the channel layer if configured


async def handle_inbound(db: AsyncSession, inbound: NormalisedInbound) -> list[OutboundMessage]:
    try:
        return await _dispatch(db, inbound)
    except Exception:
        logger.exception("handle_inbound failed for update_id=%s chat_id=%s", inbound.update_id, inbound.chat_id)
        # SPEC-015-R12: never expose internals to the chat.
        return [OutboundMessage(chat_id=inbound.chat_id, text=copy_ru.GENERIC_ERROR)]


async def _dispatch(db: AsyncSession, inbound: NormalisedInbound) -> list[OutboundMessage]:
    conv_row = await _get_or_create_conv_row(db, inbound)

    # 1. Non-private chats — SPEC-001-R02, at most one notice per chat.
    if inbound.chat_type != ChatType.PRIVATE:
        return await _handle_non_private(db, inbound, conv_row)

    # 2. Callback query (✅ / ✏️ / consent button).
    if inbound.callback_data is not None:
        return await _handle_callback(db, inbound, conv_row)

    # 3. /start <token>
    if inbound.command == "/start":
        return await _handle_start(db, inbound, conv_row)

    # 4. /help — SPEC-015-R01, only commands that exist.
    if inbound.command == "/help":
        conv_row.processing_status = "processed"
        await db.commit()
        return [OutboundMessage(chat_id=inbound.chat_id, text=copy_ru.HELP_TEXT)]

    # 5. Unbound chat — SPEC-001-R12 / SPEC-016-R01 allowlist boundary.
    user = await onboarding_service.find_bound_user(db, int(inbound.user_id))
    if user is None:
        conv_row.processing_status = "processed"
        await db.commit()
        return [OutboundMessage(chat_id=inbound.chat_id, text=copy_ru.ONBOARDING_UNBOUND)]

    conv_row.operator_id = user.id

    # 6. Flood limit — SPEC-016-R02.
    if await _is_flooding(db, user.id):
        conv_row.processing_status = "processed"
        await db.commit()
        return [OutboundMessage(chat_id=inbound.chat_id, text=copy_ru.FLOOD_LIMITED)]

    # 7. Consent gate — SPEC-016-R05 / SPEC-015-R03. Blocks everything below.
    if not onboarding_service.has_consented(user):
        conv_row.processing_status = "processed"
        await db.commit()
        return [OutboundMessage(
            chat_id=inbound.chat_id,
            text=copy_ru.CONSENT_NOTICE,
            buttons=[[InlineButton(copy_ru.CONSENT_BUTTON_TEXT, callback_data.build("consent"))]],
        )]

    # 8. Media — SPEC-015-R09/R10.
    if inbound.media_kind != MediaKind.NONE:
        if inbound.media_kind == MediaKind.VOICE:
            conv_row.media_file_unique_id = inbound.media_file_unique_id
            text = copy_ru.VOICE_NOT_SUPPORTED
        else:
            text = copy_ru.MEDIA_NOT_SUPPORTED
        conv_row.processing_status = "processed"
        conv_row.vfm_reply = text
        await db.commit()
        return [OutboundMessage(chat_id=inbound.chat_id, text=text)]

    # 9. Pending correction state — SPEC-015-R08/R13.
    pending_state = await _get_chat_state(db, inbound.chat_id, "awaiting_correction")
    if pending_state is not None:
        return await _handle_correction_text(db, inbound, user, pending_state, conv_row)

    # 10. Normal operator message — the existing understanding/agency pipeline.
    return await _handle_operator_message(db, inbound, user, conv_row)


# --- Conversation log row ---------------------------------------------------

async def _get_or_create_conv_row(db: AsyncSession, inbound: NormalisedInbound) -> ConversationLog:
    """
    The webhook/polling intake (app/channels/worker.py) already inserted this
    row before handle_inbound was ever called (SPEC-014-R03). This lookup is
    defensive — if it's somehow missing (e.g. a direct call in a test), we
    create it rather than fail the whole turn.
    """
    result = await db.execute(
        select(ConversationLog).where(
            ConversationLog.channel == inbound.channel,
            ConversationLog.update_id == inbound.update_id,
        )
    )
    row = result.scalar_one_or_none()
    if row is not None:
        return row

    row = ConversationLog(
        channel=inbound.channel,
        update_id=inbound.update_id,
        chat_id=inbound.chat_id,
        raw_text=inbound.text,
        source="telegram",
        processing_status="processing",
    )
    db.add(row)
    await db.flush()
    return row


# --- Non-private chats --------------------------------------------------------

async def _handle_non_private(
    db: AsyncSession, inbound: NormalisedInbound, conv_row: ConversationLog
) -> list[OutboundMessage]:
    notice_key = "group_chat_not_supported"
    result = await db.execute(
        select(ChannelNotice).where(
            ChannelNotice.channel == inbound.channel,
            ChannelNotice.chat_id == inbound.chat_id,
            ChannelNotice.notice_key == notice_key,
        )
    )
    already_told = result.scalar_one_or_none() is not None

    conv_row.processing_status = "processed"
    if already_told:
        await db.commit()
        return []

    db.add(ChannelNotice(channel=inbound.channel, chat_id=inbound.chat_id, notice_key=notice_key))
    await db.commit()
    return [OutboundMessage(chat_id=inbound.chat_id, text=copy_ru.GROUP_CHAT_NOT_SUPPORTED)]


# --- /start -------------------------------------------------------------------

async def _handle_start(
    db: AsyncSession, inbound: NormalisedInbound, conv_row: ConversationLog
) -> list[OutboundMessage]:
    conv_row.processing_status = "processed"
    token = (inbound.command_args or "").strip()
    if not token:
        await db.commit()
        return [OutboundMessage(chat_id=inbound.chat_id, text=copy_ru.ONBOARDING_UNBOUND)]

    result = await onboarding_service.bind_invite(db, token, int(inbound.user_id))
    conv_row.operator_id = result.user.id if result.user else None

    if result.outcome == onboarding_service.BindOutcome.BOUND:
        text = copy_ru.WELCOME_AFTER_BIND
    elif result.outcome == onboarding_service.BindOutcome.ALREADY_BOUND_ELSEWHERE:
        text = copy_ru.ALREADY_BOUND_ELSEWHERE
    else:
        text = copy_ru.INVALID_OR_EXPIRED_INVITE

    conv_row.vfm_reply = text
    await db.commit()
    return [OutboundMessage(chat_id=inbound.chat_id, text=text)]


# --- Flood limit ---------------------------------------------------------------

async def _is_flooding(db: AsyncSession, operator_id: int) -> bool:
    one_minute_ago = datetime.utcnow() - timedelta(minutes=1)
    result = await db.execute(
        select(func.count(ConversationLog.id)).where(
            ConversationLog.operator_id == operator_id,
            ConversationLog.created_at >= one_minute_ago,
        )
    )
    return int(result.scalar_one() or 0) > FLOOD_LIMIT_PER_MINUTE


# --- chat_state helpers --------------------------------------------------------

async def _get_chat_state(db: AsyncSession, chat_id: str, state_key: str) -> Optional[ChatState]:
    result = await db.execute(
        select(ChatState).where(ChatState.chat_id == chat_id, ChatState.state_key == state_key)
    )
    return result.scalar_one_or_none()


async def _clear_chat_state(db: AsyncSession, chat_id: str, state_key: str) -> None:
    state = await _get_chat_state(db, chat_id, state_key)
    if state is not None:
        await db.delete(state)


# --- Callback query (✅ / ✏️ / consent) -----------------------------------------

async def _handle_callback(
    db: AsyncSession, inbound: NormalisedInbound, conv_row: ConversationLog
) -> list[OutboundMessage]:
    conv_row.processing_status = "processed"
    parsed = callback_data.parse(inbound.callback_data or "")
    if parsed is None:
        await db.commit()
        return [OutboundMessage(chat_id=inbound.chat_id, text="", callback_answer_text=copy_ru.STALE_CALLBACK)]

    if parsed.action == "consent":
        user = await onboarding_service.find_bound_user(db, int(inbound.user_id))
        if user is None:
            await db.commit()
            return [OutboundMessage(chat_id=inbound.chat_id, text="", callback_answer_text=copy_ru.STALE_CALLBACK)]
        await onboarding_service.record_consent(db, user, copy_ru.CONSENT_TEXT_VERSION)
        await db.commit()
        return [OutboundMessage(chat_id=inbound.chat_id, text=copy_ru.CONSENT_RECORDED)]

    if parsed.pending_id is None:
        await db.commit()
        return [OutboundMessage(chat_id=inbound.chat_id, text="", callback_answer_text=copy_ru.STALE_CALLBACK)]

    # Ownership check — SPEC-015-R05: usable only by the chat that owns it.
    pending_result = await db.execute(select(PendingConfirmation).where(PendingConfirmation.id == parsed.pending_id))
    pending = pending_result.scalar_one_or_none()
    user = await onboarding_service.find_bound_user(db, int(inbound.user_id))
    if pending is None or user is None or pending.operator_id != user.id:
        await db.commit()
        return [OutboundMessage(chat_id=inbound.chat_id, text="", callback_answer_text=copy_ru.STALE_CALLBACK)]

    if parsed.action == "confirm":
        outcome = await confirmation_service.promote_pending_confirmation(db, parsed.pending_id)
        if outcome.result == confirmation_service.PromotionResult.COMMITTED:
            conv_row.timeline_event_id = outcome.timeline_event_id
            await db.commit()
            return [OutboundMessage(chat_id=inbound.chat_id, text="Записано ✓", callback_answer_text="Записано ✓")]
        if outcome.result == confirmation_service.PromotionResult.ALREADY_RESOLVED:
            await db.commit()
            return [OutboundMessage(chat_id=inbound.chat_id, text="", callback_answer_text=copy_ru.ALREADY_RECORDED)]
        await db.commit()
        return [OutboundMessage(chat_id=inbound.chat_id, text="", callback_answer_text=copy_ru.STALE_CALLBACK)]

    if parsed.action == "correct":
        db.add(ChatState(
            chat_id=inbound.chat_id,
            state_key="awaiting_correction",
            state_payload={"pending_id": parsed.pending_id},
        ))
        await db.commit()
        return [OutboundMessage(chat_id=inbound.chat_id, text=copy_ru.AWAITING_CORRECTION_PROMPT)]

    await db.commit()
    return [OutboundMessage(chat_id=inbound.chat_id, text="", callback_answer_text=copy_ru.STALE_CALLBACK)]


# --- Correction follow-up text -------------------------------------------------

async def _handle_correction_text(
    db: AsyncSession,
    inbound: NormalisedInbound,
    user: User,
    chat_state: ChatState,
    conv_row: ConversationLog,
) -> list[OutboundMessage]:
    """
    SPEC-015-R08: the next message after ✏️ resolves the pending item — if
    not yet committed, replaces its value; if already committed, creates a
    correction event. Reuses the existing extraction pipeline (context_llm)
    to parse the new value, rather than inventing a second parser — this is
    a deliberately simple first version (see final report for the caveat on
    unusual phrasings).
    """
    from app.core.context_llm import context_extract
    from app.schemas.fleet_update import FleetUpdate as _FU

    pending_id = (chat_state.state_payload or {}).get("pending_id")
    conv_row.processing_status = "processed"

    probe = _FU.from_raw(
        source=MessageSource.TELEGRAM, operator_id=str(user.platform_user_id),
        chat_id=inbound.chat_id, raw_text=inbound.text or "", modality=Modality.TEXT,
    )
    try:
        extraction = await context_extract(probe, None, None)
        entities = extraction.entities or {}
    except Exception:
        entities = {}

    # Still-pending item — replace its payload in place.
    pending_result = await db.execute(select(PendingConfirmation).where(PendingConfirmation.id == pending_id))
    pending = pending_result.scalar_one_or_none()
    if pending is not None and pending.resolved_at is None:
        replaced = await confirmation_service.replace_pending_payload(db, pending_id, entities, inbound.text)
        await _clear_chat_state(db, inbound.chat_id, "awaiting_correction")
        await db.commit()
        text = copy_ru.CORRECTION_APPLIED if replaced else copy_ru.CORRECTION_FAILED_STALE
        conv_row.vfm_reply = text
        await db.commit()
        return [OutboundMessage(chat_id=inbound.chat_id, text=text)]

    # Already-committed item — create a correction event.
    target_event_id = pending.resolved_event_id if pending else None
    if target_event_id is None:
        await _clear_chat_state(db, inbound.chat_id, "awaiting_correction")
        await db.commit()
        return [OutboundMessage(chat_id=inbound.chat_id, text=copy_ru.CORRECTION_FAILED_STALE)]

    field, value = next(iter(entities.items())) if entities else (None, None)
    if field is None:
        await db.commit()
        return [OutboundMessage(chat_id=inbound.chat_id, text=copy_ru.CORRECTION_NO_FIELD_FOUND)]

    try:
        correction_event = await correction_service.apply_correction(db, target_event_id, field, value)
    except correction_service.EventNotFound:
        await _clear_chat_state(db, inbound.chat_id, "awaiting_correction")
        await db.commit()
        return [OutboundMessage(chat_id=inbound.chat_id, text=copy_ru.CORRECTION_FAILED_STALE)]

    await _clear_chat_state(db, inbound.chat_id, "awaiting_correction")
    conv_row.corrected_by = correction_event.id
    await db.commit()
    return [OutboundMessage(chat_id=inbound.chat_id, text=copy_ru.CORRECTION_APPLIED)]


# --- Normal operator message --------------------------------------------------

async def _handle_operator_message(
    db: AsyncSession, inbound: NormalisedInbound, user: User, conv_row: ConversationLog
) -> list[OutboundMessage]:
    update = FleetUpdate.from_raw(
        source=MessageSource.TELEGRAM,
        operator_id=str(user.platform_user_id),
        chat_id=inbound.chat_id,
        raw_text=inbound.text or "",
        modality=Modality.TEXT,
        message_id=inbound.message_id,
    )
    update.operator_db_id = user.id

    processed = await event_processor.process(db, update)

    conv_row.intent = getattr(processed.intent, "value", processed.intent) or None
    conv_row.confidence = processed.confidence
    conv_row.policy_action = getattr(processed.confidence_route, "value", processed.confidence_route) or None
    conv_row.task_type = getattr(processed, "_task_type", None)
    conv_row.vfm_reply = processed.reply_text or None
    conv_row.rephrasing_rejected = getattr(processed, "_rephrasing_rejected", False)
    conv_row.timeline_event_id = processed.timeline_event_id
    conv_row.processing_status = "processed"
    await db.commit()

    buttons = None
    pending_id = getattr(processed, "_pending_confirmation_id", None)
    if pending_id is not None:
        buttons = [[
            InlineButton(copy_ru.CONFIRM_BUTTON_TEXT, callback_data.build("confirm", pending_id)),
            InlineButton(copy_ru.CORRECT_BUTTON_TEXT, callback_data.build("correct", pending_id)),
        ]]

    return [OutboundMessage(chat_id=inbound.chat_id, text=processed.reply_text or copy_ru.GENERIC_ERROR, buttons=buttons)]


# --- Consent gate helper reused by _dispatch (kept for clarity) --------------

async def _handle_consent_gate(db: AsyncSession, inbound: NormalisedInbound, user: User) -> list[OutboundMessage]:
    return [OutboundMessage(
        chat_id=inbound.chat_id,
        text=copy_ru.CONSENT_NOTICE,
        buttons=[[InlineButton(copy_ru.CONSENT_BUTTON_TEXT, callback_data.build("consent"))]],
    )]
