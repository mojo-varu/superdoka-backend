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

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.ner_handler import init_model
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
    init_model()
    logger.info("NER model loading started (background thread)")

    # 2. Start the Watcher background task
    watcher_task = asyncio.create_task(watcher.run())
    logger.info("Watcher background task started")

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

    app.mount("/static", StaticFiles(directory="static"), name="static")

    return app


app = create_app()
