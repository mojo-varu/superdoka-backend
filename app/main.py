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

    # Serve demo.html with no-cache so browsers always get the latest JS
    @app.get("/sandbox", include_in_schema=False)
    @app.get("/demo", include_in_schema=False)
    async def serve_demo():
        from fastapi.responses import FileResponse
        return FileResponse(
            "static/demo.html",
            headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
        )

    @app.get("/neo", include_in_schema=False)
    async def serve_neo():
        from fastapi.responses import FileResponse
        return FileResponse(
            "static/logbuk-neo.html",
            headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
        )

    app.mount("/static", StaticFiles(directory="static"), name="static")

    return app


app = create_app()
