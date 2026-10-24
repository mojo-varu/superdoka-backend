"""
app/channels/settings.py

Bot-runtime configuration. Deliberately separate from app/config.py's
Settings — the main FastAPI app (sandbox, REST API) must keep booting even
when no Telegram env vars are set at all. BotSettings is only constructed
when the bot channel is actually started (webhook route registration,
polling entry point, admin CLI) — see get_bot_settings().

SPEC-014-R01, R06. ADR-0021 (separate dev/prod tokens, deployed twice).

NEVER log, print, or include any of these values (especially bot_token,
webhook_secret) in an exception message. SPEC-016-R03.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


class BotConfigError(RuntimeError):
    """Raised at startup when a required bot setting is missing or invalid.
    The message names the missing variable, never its value."""


@dataclass(frozen=True)
class BotSettings:
    mode: str              # "polling" | "webhook"
    bot_env: str           # "dev" | "prod"
    bot_token: str
    webhook_secret: str | None
    webhook_base_url: str | None
    database_url: str
    worker_concurrency: int
    stuck_row_threshold_seconds: int
    flood_limit_per_minute: int
    callback_expiry_hours: int


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise BotConfigError(f"Missing required environment variable: {name}")
    return value


def get_bot_settings() -> BotSettings:
    """
    Fail fast with a clear message (naming the variable, never a value) if
    anything required is missing. Call this at bot startup (webhook route
    registration, polling entry point, admin CLI) — not at module import
    time, so the rest of the app is unaffected if these vars are absent.
    """
    mode = os.getenv("TELEGRAM_MODE", "polling").lower()
    if mode not in ("polling", "webhook"):
        raise BotConfigError(
            "TELEGRAM_MODE must be 'polling' or 'webhook', got: "
            f"{mode!r} (value redacted-safe: this is not a secret)"
        )

    bot_env = os.getenv("BOT_ENV", "dev").lower()
    if bot_env not in ("dev", "prod"):
        raise BotConfigError(f"BOT_ENV must be 'dev' or 'prod', got an unrecognised value")

    # ADR-0021: separate dev/prod tokens, never shared.
    token_var = "TELEGRAM_BOT_TOKEN_PROD" if bot_env == "prod" else "TELEGRAM_BOT_TOKEN_DEV"
    bot_token = _require(token_var)

    webhook_secret = os.getenv("WEBHOOK_SECRET") or None
    webhook_base_url = os.getenv("WEBHOOK_BASE_URL") or None
    if mode == "webhook":
        if not webhook_secret:
            raise BotConfigError("Missing required environment variable: WEBHOOK_SECRET (required when TELEGRAM_MODE=webhook)")
        if not webhook_base_url:
            raise BotConfigError("Missing required environment variable: WEBHOOK_BASE_URL (required when TELEGRAM_MODE=webhook)")

    database_url = _require("DATABASE_URL")

    return BotSettings(
        mode=mode,
        bot_env=bot_env,
        bot_token=bot_token,
        webhook_secret=webhook_secret,
        webhook_base_url=webhook_base_url,
        database_url=database_url,
        worker_concurrency=int(os.getenv("BOT_WORKER_CONCURRENCY", "3")),           # OQ-014-2: conservative default for ~5 owners/50 operators
        stuck_row_threshold_seconds=int(os.getenv("BOT_STUCK_ROW_SECONDS", "300")),  # SPEC-001-R10 / SPEC-014-R05 starting value: 5 minutes
        flood_limit_per_minute=int(os.getenv("BOT_FLOOD_LIMIT_PER_MINUTE", "20")),   # SPEC-016 OQ-016-2 starting value
        callback_expiry_hours=int(os.getenv("BOT_CALLBACK_EXPIRY_HOURS", "24")),     # SPEC-015 OQ-015-2 / ADR-0023 starting value
    )
