"""
app/main.py

Updated to:
  1. Register the /api/v1/vfm router
  2. Start the Watcher background task on startup
  3. Gracefully stop the Watcher on shutdown
  4. Warm the Redis session cache from Postgres on startup

Everything else (existing routers, NER init, DB init) is preserved.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

# from app.core.ner_handler import init_model
from app.services.watcher import watcher

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan — replaces @app.on_event("startup") / ("shutdown")
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────────
    logger.info("Starting up VFM backend...")

    # 1. Start NER model loading in background thread (existing behaviour)
    # init_model()
    # logger.info("NER model loading started (background thread)")

    # 2. Preload persona into lru_cache before first request
    from app.core.persona import load_persona
    load_persona()
    logger.info("VFM persona loaded")

    # 3. Start ONNX pipeline models loading (non-blocking)
    from app.core.model_loader import load_models
    load_models(blocking=False)
    logger.info("ONNX pipeline models loading started (background)")

    # 4. Start the Watcher background task
    watcher_task = asyncio.create_task(watcher.run())
    logger.info("Watcher background task started")

    # 5. Start the bot worker (WP-A/WP-C) — only if the bot is configured.
    # The main app must keep booting (sandbox, REST-only deployments) even
    # with no Telegram env vars set at all; get_bot_settings() fails fast
    # by design, so we catch that specific case here rather than letting it
    # take the whole app down.
    bot_worker_task = None
    poll_task = None
    try:
        from app.channels.settings import get_bot_settings
        bot_settings = get_bot_settings()   # raises BotConfigError if unconfigured — never logs the values either way
        from app.channels.worker import worker as bot_worker
        bot_worker_task = asyncio.create_task(bot_worker.run())
        logger.info("Bot worker background task started")

        # TELEGRAM_MODE=polling: run the poll loop in this same process too,
        # so local dev is a single `uvicorn app.main:app --reload` command —
        # no second terminal, and no second Worker instance polling the same
        # table (that would just be wasted contention now that the claim in
        # app/channels/worker.py is atomic, but there's still no reason to run
        # two in dev). `python -m app.channels.telegram.polling` remains
        # available as a standalone entry point if ever needed separately.
        if bot_settings.mode == "polling":
            from app.channels.telegram.polling import _poll_loop
            poll_task = asyncio.create_task(_poll_loop())
            logger.info("Telegram polling loop started in-process (TELEGRAM_MODE=polling)")
    except Exception as e:
        logger.info(f"Bot worker not started (bot channel unconfigured or failed init): {e}")

    yield   # ← application runs here

    # ── Shutdown ─────────────────────────────────────────────────────────
    logger.info("Shutting down...")
    watcher.stop()
    watcher_task.cancel()
    try:
        await watcher_task
    except asyncio.CancelledError:
        pass
    logger.info("Watcher stopped cleanly")

    if bot_worker_task is not None:
        from app.channels.worker import worker as bot_worker
        bot_worker.stop()
        bot_worker_task.cancel()
        try:
            await bot_worker_task
        except asyncio.CancelledError:
            pass
        logger.info("Bot worker stopped cleanly")

    if poll_task is not None:
        poll_task.cancel()
        try:
            await poll_task
        except asyncio.CancelledError:
            pass
        logger.info("Telegram polling loop stopped cleanly")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    app = FastAPI(
        title       = "Logbuk — Virtual Fleet Manager API",
        description = "Fleet management backend with NER, context engine, and rule-based agency",
        version     = "2.0.0",
        lifespan    = lifespan,
    )

    # ── Existing routers (keep exactly as-is) ────────────────────────────
    from app.api.v1.api import api_router          # your existing v1 router
    app.include_router(api_router, prefix="/api/v1")

    # WP-C: the Telegram webhook route lives inside this same app/process
    # (ADR-0020 — not a separate web service). Registered unconditionally;
    # the route itself calls get_bot_settings() per-request and will 500
    # with a clear error if the bot isn't configured, rather than needing a
    # second feature flag here.
    from app.channels.telegram.webhook import router as telegram_webhook_router
    app.include_router(telegram_webhook_router, prefix="/api/v1")

    # SPEC-014-R07: health endpoint distinct from liveness. "status: ok"
    # here only means the process is up and can read its own config —
    # it does not probe the database or Telegram.
    @app.get("/health", include_in_schema=False)
    async def health():
        return {"status": "ok"}

    # Log every 422 with the full input so we can see what the client sent
    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        errors = exc.errors()
        # Pydantic v2 includes the full input in errors[*]["input"]
        inputs = {e.get("loc", [])[-1]: e.get("input") for e in errors if e.get("input")}
        logger.warning(
            "422 on %s %s — missing/invalid: %s — received input: %s",
            request.method, request.url.path,
            [e.get("loc") for e in errors],
            inputs,
        )
        return JSONResponse(status_code=422, content={"detail": errors})

    @app.get("/", include_in_schema=False)
    @app.get("/sandbox", include_in_schema=False)
    @app.get("/sandbox.html", include_in_schema=False)
    async def serve_sandbox():
        from fastapi.responses import FileResponse
        return FileResponse(
            "static/sandbox.html",
            headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
        )

    app.mount("/static", StaticFiles(directory="static"), name="static")

    return app


app = create_app()
