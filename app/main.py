# app/main.py
from app.api.v1.api import api_router
from app.api.ui import ui_router
from fastapi import FastAPI
from app.core.ner_handler import init_model
from app.db.database import engine
from app.db.base import Base

app = FastAPI()
app.include_router(api_router, prefix="/api/v1")
app.include_router(ui_router)

@app.on_event("startup")
async def startup_event():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Init both models in background threads
    init_model()
