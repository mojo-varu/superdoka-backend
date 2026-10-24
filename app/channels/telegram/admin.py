"""
app/channels/telegram/admin.py

`python -m app.channels.telegram.admin set-webhook|delete-webhook|info`

SPEC-014-R06: never prints the bot token under any subcommand or error
path. Refuses to start polling in BOT_ENV=prod while a webhook is set
(the actual refusal lives in polling.py; webhook_is_set() here is the
shared check both use).
"""
from __future__ import annotations

import asyncio
import sys

from app.channels.settings import get_bot_settings


async def webhook_is_set() -> bool:
    from app.channels.telegram.bot import get_bot
    bot = get_bot()
    info = await bot.get_webhook_info()
    url = getattr(info, "url", None) or (info.get("url") if isinstance(info, dict) else None)
    return bool(url)


async def cmd_info() -> None:
    from app.channels.telegram.bot import get_bot
    settings = get_bot_settings()
    bot = get_bot()
    info = await bot.get_webhook_info()
    url = getattr(info, "url", None) or (info.get("url") if isinstance(info, dict) else None)
    last_error = getattr(info, "last_error_message", None) or (info.get("last_error_message") if isinstance(info, dict) else None)
    # Deliberately prints only non-secret fields — never the token.
    print(f"bot_env={settings.bot_env} mode={settings.mode}")
    print(f"webhook_url={url or '(none — polling or unset)'}")
    print(f"last_error_message={last_error or '(none)'}")


async def cmd_set_webhook() -> None:
    from app.channels.telegram.bot import get_bot
    settings = get_bot_settings()
    if not settings.webhook_base_url:
        print("ERROR: WEBHOOK_BASE_URL is not set.", file=sys.stderr)
        sys.exit(1)
    bot = get_bot()
    url = f"{settings.webhook_base_url.rstrip('/')}/api/v1/channels/telegram/webhook"
    await bot.set_webhook(url=url, secret_token=settings.webhook_secret)
    print(f"Webhook set (url printed is not secret): {url}")


async def cmd_delete_webhook() -> None:
    from app.channels.telegram.bot import get_bot
    bot = get_bot()
    await bot.delete_webhook()
    print("Webhook deleted.")


async def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m app.channels.telegram.admin set-webhook|delete-webhook|info", file=sys.stderr)
        sys.exit(2)

    command = sys.argv[1]
    if command == "info":
        await cmd_info()
    elif command == "set-webhook":
        settings = get_bot_settings()
        if settings.bot_env == "prod":
            # SPEC-014-R06's prod/polling guard is specifically about polling;
            # setting a webhook in prod is the expected path, no refusal here.
            pass
        await cmd_set_webhook()
    elif command == "delete-webhook":
        await cmd_delete_webhook()
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    asyncio.run(main())
