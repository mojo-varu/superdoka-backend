"""
app/channels/telegram/webhook.py

WP-C: the webhook route, mounted into the EXISTING FastAPI app (same
process, same api service in docker-compose.yml / docker-compose.prod.yml —
not a separate web service; SPEC-014-R02/R03).

Verifies Telegram's secret-token header before any database access
(constant-time comparison), inserts the inbound row, returns fast. All
actual processing happens in the worker (app/channels/worker.py).
"""
from __future__ import annotations

import hmac
import logging

from fastapi import APIRouter, Header, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from app.channels.settings import get_bot_settings
from app.channels.telegram.bot import parse_inbound
from app.channels.worker import insert_received_row
from app.db.database import get_async_session

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/channels/telegram", tags=["Telegram Bot"])


@router.post("/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
    db: AsyncSession = Depends(get_async_session),
) -> Response:
    # SPEC-014-R02: verify before any database access.
    settings = get_bot_settings()
    provided = x_telegram_bot_api_secret_token or ""
    expected = settings.webhook_secret or ""
    if not expected or not hmac.compare_digest(provided, expected):
        logger.warning("Webhook request rejected: missing or incorrect secret token")
        return Response(status_code=401)

    raw_update = await request.json()
    inbound = parse_inbound(raw_update)
    if inbound is None:
        # An update type we don't handle (e.g. edited_message) — ack anyway,
        # Telegram should not retry something we're intentionally ignoring.
        return Response(status_code=200)

    # SPEC-014-R03: insert and return fast; duplicates are a no-op.
    await insert_received_row(db, inbound)
    return Response(status_code=200)
