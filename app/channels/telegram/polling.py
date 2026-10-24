"""
app/channels/telegram/polling.py

`python -m app.channels.telegram.polling` — local-dev intake mode
(TELEGRAM_MODE=polling). Shares insert_received_row with webhook.py
(SPEC-014-R01) and the same worker consumes rows either way — polling only
replaces how rows get into the `received` state, not what happens after.

The admin CLI refuses to combine this with BOT_ENV=prod while a webhook is
set (see admin.py) — never run polling against the prod token with a
webhook active.
"""
from __future__ import annotations

import asyncio
import logging

from app.channels.settings import get_bot_settings
from app.channels.telegram.bot import get_bot, parse_inbound
from app.channels.worker import insert_received_row, worker
from app.db.database import get_async_session

logger = logging.getLogger(__name__)
POLL_TIMEOUT_SECONDS = 30


async def _poll_loop() -> None:
    settings = get_bot_settings()
    if settings.bot_env == "prod":
        from app.channels.telegram.admin import webhook_is_set
        if await webhook_is_set():
            raise RuntimeError(
                "Refusing to start polling: BOT_ENV=prod and a webhook is currently set. "
                "Delete the webhook first via the admin CLI if polling is genuinely intended."
            )

    bot = get_bot()
    offset: int | None = None
    logger.info("Telegram polling started (bot_env=%s)", settings.bot_env)

    while True:
        try:
            updates = await bot.get_updates(offset=offset, timeout=POLL_TIMEOUT_SECONDS)
        except Exception:
            logger.exception("get_updates failed, retrying shortly")
            await asyncio.sleep(2)
            continue

        for update in updates:
            raw = update.model_dump(mode="json") if hasattr(update, "model_dump") else dict(update)
            offset = raw["update_id"] + 1
            inbound = parse_inbound(raw)
            if inbound is None:
                continue
            async for db in get_async_session():
                await insert_received_row(db, inbound)
                break


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    worker_task = asyncio.create_task(worker.run())
    try:
        await _poll_loop()
    finally:
        worker.stop()
        worker_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
