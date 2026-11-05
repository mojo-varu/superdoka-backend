"""
app/channels/worker.py

WP-C: acknowledge-fast, process-in-worker. SPEC-014-R03/R04/R05.

Entry points:
  - insert_received_row(): called by webhook.py and polling.py, inserts the
    inbound row and returns immediately — this is the "acknowledge fast"
    half.
  - Worker.run(): the "process in worker" half — an asyncio loop started
    with the app (app/main.py) or as its own process
    (`python -m app.channels.worker` for the production instance, per
    SPEC-014-R04).

At most one message per chat in flight at a time (per-chat ordering,
SPEC-014-R04); overall concurrency capped by BotSettings.worker_concurrency.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.base import NormalisedInbound, OutboundMessage
from app.channels.settings import get_bot_settings
from app.db.database import get_async_session
from app.db.models import ConversationLog

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 1.0


async def insert_received_row(db: AsyncSession, inbound: NormalisedInbound) -> bool:
    """
    SPEC-014-R03/SPEC-001-R08: insert before running the pipeline, return
    success fast. Returns False on a duplicate (channel, update_id) — the
    caller (webhook.py) still returns HTTP 200 either way, it just skips
    enqueueing a second time.
    """
    row = ConversationLog(
        channel=inbound.channel,
        update_id=inbound.update_id,
        chat_id=inbound.chat_id,
        raw_text=inbound.text,
        media_file_unique_id=inbound.media_file_unique_id,
        raw_update=inbound.raw,
        source="telegram",
        processing_status="received",
    )
    db.add(row)
    try:
        await db.commit()
        return True
    except IntegrityError:
        await db.rollback()
        logger.info("Duplicate inbound update (channel=%s, update_id=%s) — skipped", inbound.channel, inbound.update_id)
        return False


class Worker:
    def __init__(self) -> None:
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._in_flight_chats: set[str] = set()

    async def run(self) -> None:
        self._running = True
        logger.info("Bot worker started")
        while self._running:
            try:
                await self._drain_once()
            except Exception:
                logger.exception("Worker drain loop error")
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    def stop(self) -> None:
        self._running = False

    async def _drain_once(self) -> None:
        settings = get_bot_settings()
        async for db in get_async_session():
            await self._recover_stuck_rows(db, settings.stuck_row_threshold_seconds)

            result = await db.execute(
                select(ConversationLog)
                .where(ConversationLog.processing_status == "received")
                .order_by(ConversationLog.id)
                .limit(50)
            )
            rows = result.scalars().all()

            claimed = 0
            for row in rows:
                if claimed >= settings.worker_concurrency:
                    break
                if row.chat_id in self._in_flight_chats:
                    continue   # per-chat ordering — skip, pick up next drain cycle
                claimed += 1
                self._in_flight_chats.add(row.chat_id)
                asyncio.create_task(self._process_row(row.id))
            return   # one db session per drain tick

    async def _recover_stuck_rows(self, db: AsyncSession, threshold_seconds: int) -> None:
        """SPEC-001-R10/SPEC-014-R05: re-claim rows stuck in 'processing' past
        the threshold (a crashed worker never silently drops a message)."""
        cutoff = datetime.utcnow() - timedelta(seconds=threshold_seconds)
        result = await db.execute(
            select(ConversationLog).where(
                ConversationLog.processing_status == "processing",
                ConversationLog.claimed_at < cutoff,
            )
        )
        stuck = result.scalars().all()
        for row in stuck:
            logger.warning("Re-claiming stuck conversation_log row id=%s (claimed_at=%s)", row.id, row.claimed_at)
            row.processing_status = "received"
            row.claimed_at = None
        if stuck:
            await db.commit()

    async def _process_row(self, row_id: int) -> None:
        from app.channels.telegram.bot import parse_inbound
        from app.channels.telegram.delivery import UserUnreachable, send_with_resilience
        from app.services.engine_entrypoint import handle_inbound

        chat_id_for_release: Optional[str] = None
        try:
            async for db in get_async_session():
                # Atomic claim: the WHERE guard means only one process can ever
                # flip this row from 'received' to 'processing', even when more
                # than one Worker polls the same table concurrently (SPEC-014-R04
                # sanctions a separate `python -m app.channels.worker` process
                # alongside the in-app one — the old select-then-update here had
                # a race window between two such processes).
                claim = await db.execute(
                    update(ConversationLog)
                    .where(ConversationLog.id == row_id, ConversationLog.processing_status == "received")
                    .values(processing_status="processing", claimed_at=datetime.utcnow())
                )
                await db.commit()
                if claim.rowcount != 1:
                    return   # already claimed by another worker, or no longer 'received'

                result = await db.execute(select(ConversationLog).where(ConversationLog.id == row_id))
                row = result.scalar_one()
                chat_id_for_release = row.chat_id

                inbound = parse_inbound(row.raw_update or {})
                if inbound is None:
                    row.processing_status = "processed"
                    await db.commit()
                    return

                outbound_messages: list[OutboundMessage] = await handle_inbound(db, inbound)
                await self._deliver(outbound_messages, send_with_resilience)
                return
        except Exception:
            logger.exception("Worker failed processing conversation_log row id=%s", row_id)
            async for db in get_async_session():
                result = await db.execute(select(ConversationLog).where(ConversationLog.id == row_id))
                row = result.scalar_one_or_none()
                if row is not None:
                    row.processing_status = "failed"
                    await db.commit()
                return
        finally:
            if chat_id_for_release is not None:
                self._in_flight_chats.discard(chat_id_for_release)

    async def _deliver(self, messages: list[OutboundMessage], send_fn) -> None:
        from app.channels.telegram.bot import get_bot
        from app.channels.telegram.delivery import UserUnreachable

        for msg in messages:
            if not msg.text and not msg.callback_answer_text:
                continue
            try:
                bot = get_bot()

                async def _send(chat_id: str, text: str, reply_markup=None) -> None:
                    await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)

                if msg.text:
                    await send_fn(_send, msg.chat_id, msg.text, _build_markup(msg))
            except UserUnreachable:
                logger.info("Chat %s unreachable (blocked/deactivated) — marking and dropping reply", msg.chat_id)
                async for db in get_async_session():
                    await _mark_unreachable(db, msg.chat_id)
                    return


def _build_markup(msg: OutboundMessage):
    if not msg.buttons:
        return None
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup   # local import, see bot.py note
    rows = [
        [InlineKeyboardButton(text=b.text, callback_data=b.callback_data) for b in row]
        for row in msg.buttons
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _mark_unreachable(db: AsyncSession, chat_id: str) -> None:
    from app.db.models import User
    result = await db.execute(select(User).where(User.platform_user_id == int(chat_id)))
    user = result.scalar_one_or_none()
    if user is not None:
        user.is_reachable = False
        await db.commit()


worker = Worker()


async def main() -> None:
    """`python -m app.channels.worker` — the production instance's separate
    worker process (SPEC-014-R04)."""
    logging.basicConfig(level=logging.INFO)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
