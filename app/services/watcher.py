"""
app/services/watcher.py  — Hour 8a

Background asyncio task that runs independently of the request path.
Handles time-based and state-based triggers:

  Every 5 min:  drain pending group_messages queue
  Every 15 min: fuel anomaly scan across active sessions
  Every 5 min:  no-checkin nudges for operators overdue
  On schedule:  morning nudge at configured time
  On SHIFT_END: reconciliation (fired by EventProcessor, not here)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_async_session
from app.db.models import ActiveSession, GroupMessage, OwnerSettings, ProcessingStatus
from app.schemas.fleet_update import FleetUpdate, MessageSource, Modality
from app.services.event_processor import event_processor
from app.services.rule_engine import rule_engine

logger = logging.getLogger(__name__)

MAX_RETRIES    = 3
QUEUE_INTERVAL = 300    # 5 min — queue drain
NUDGE_INTERVAL = 300    # 5 min — checkin nudge check


class Watcher:
    """
    Runs as a background asyncio task.
    Start via:  asyncio.create_task(watcher.run())
    Stop via:   watcher.stop()
    """

    def __init__(self):
        self._running   = False
        self._task_refs = []

    async def run(self) -> None:
        self._running = True
        logger.info("Watcher started")
        self._task_refs = [
            asyncio.create_task(self._queue_drain_loop()),
            asyncio.create_task(self._nudge_loop()),
        ]
        await asyncio.gather(*self._task_refs, return_exceptions=True)

    def stop(self) -> None:
        self._running = False
        for t in self._task_refs:
            t.cancel()
        logger.info("Watcher stopped")

    # ── Queue drain loop ──────────────────────────────────────────────────

    async def _queue_drain_loop(self) -> None:
        while self._running:
            try:
                await self._drain_pending_messages()
            except Exception as e:
                logger.error(f"Queue drain error: {e}")
            await asyncio.sleep(QUEUE_INTERVAL)

    async def _drain_pending_messages(self) -> None:
        """
        Pull pending group_messages and run them through EventProcessor.
        Uses retry_count + last_error for failure resilience.
        """
        async for db in get_async_session():
            result = await db.execute(
                select(GroupMessage).where(
                    GroupMessage.processing_status.in_([
                        ProcessingStatus.PENDING.value,
                        ProcessingStatus.PROCESSING.value,   # recover stalled
                    ]),
                    GroupMessage.retry_count < MAX_RETRIES,
                ).order_by(GroupMessage.created_at).limit(50)
            )
            messages = result.scalars().all()

            if not messages:
                return

            logger.info(f"Watcher: draining {len(messages)} pending messages")

            for msg in messages:
                await self._process_one(db, msg)

    async def _process_one(self, db: AsyncSession, msg: GroupMessage) -> None:
        # Mark as processing (prevents parallel workers picking it up)
        msg.processing_status = ProcessingStatus.PROCESSING.value
        await db.commit()

        try:
            update = FleetUpdate.from_raw(
                source         = MessageSource(msg.source),
                operator_id    = str(msg.telegram_user_id),
                chat_id        = str(msg.group_id),
                raw_text       = msg.message_text,
                modality       = Modality.TEXT,
                message_id     = str(msg.telegram_message_id),
            )

            processed = await event_processor.process(db, update)

            msg.processing_status = ProcessingStatus.PROCESSED.value
            msg.parsed_data       = str(processed.entities)
            msg.timeline_event_id = processed.timeline_event_id
            await db.commit()

            logger.info(
                f"Message {msg.id} processed → intent={processed.intent} "
                f"confidence={processed.confidence:.2f}"
            )

        except Exception as e:
            msg.retry_count += 1
            msg.last_error   = str(e)[:500]
            if msg.retry_count >= MAX_RETRIES:
                msg.processing_status = ProcessingStatus.FAILED.value
                msg.failed_at         = datetime.utcnow()
                logger.error(
                    f"Message {msg.id} permanently failed after {MAX_RETRIES} retries: {e}"
                )
            else:
                msg.processing_status = ProcessingStatus.PENDING.value
                logger.warning(
                    f"Message {msg.id} retry {msg.retry_count}/{MAX_RETRIES}: {e}"
                )
            await db.commit()

    # ── Nudge loop ────────────────────────────────────────────────────────

    async def _nudge_loop(self) -> None:
        while self._running:
            try:
                await self._check_nudges()
            except Exception as e:
                logger.error(f"Nudge loop error: {e}")
            await asyncio.sleep(NUDGE_INTERVAL)

    async def _check_nudges(self) -> None:
        """
        For each active session, check if the operator is overdue
        for a check-in and fire the no_checkin_nudge rule if so.
        """
        async for db in get_async_session():
            result = await db.execute(
                select(ActiveSession).where(
                    ActiveSession.shift_state == "ACTIVE"
                )
            )
            sessions = result.scalars().all()

            for session in sessions:
                # Look up owner settings for this operator's machine
                settings = await self._get_owner_settings(db, session.machine_id)
                interval_hours = settings.checkin_interval_hours if settings else 4

                minutes_on_shift = int(
                    (datetime.utcnow() - session.started_at).total_seconds() / 60
                )
                # Only nudge if: on shift long enough AND no recent checkin
                minutes_since_seen = int(
                    (datetime.utcnow() - session.last_seen_at).total_seconds() / 60
                )

                if (
                    minutes_on_shift >= interval_hours * 60
                    and minutes_since_seen >= interval_hours * 60
                ):
                    ctx = {
                        "session": {
                            "operator_id":      session.operator_id,
                            "machine_id":       session.machine_id,
                            "minutes_on_shift": minutes_on_shift,
                            "checkin_count":    session.checkin_count,
                            "machine_reg":      "",   # TODO: join Machine table
                        }
                    }
                    actions = await rule_engine.evaluate_watcher_rules(ctx)
                    for action in actions:
                        logger.info(
                            f"Watcher nudge → operator {session.operator_id}: {action.message}"
                        )
                        # TODO: send via adapter

    async def _get_owner_settings(
        self, db: AsyncSession, machine_id: int
    ) -> "OwnerSettings | None":
        # Simplified — in production join through Machine → User → OwnerSettings
        return None


watcher = Watcher()
