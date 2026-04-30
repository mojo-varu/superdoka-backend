import os
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite+aiosqlite:///./vfm_dev.db",   # local dev fallback (no Docker needed)
)

# asyncpg (Postgres) and aiosqlite (SQLite) are both supported.
# The connect_args below are SQLite-specific — asyncpg ignores unknown kwargs,
# so this is safe to leave for both drivers.
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_async_engine(
    DATABASE_URL,
    connect_args=connect_args,
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_async_session():
    async with AsyncSessionLocal() as session:
        yield session


get_db = get_async_session


async def init_db():
    """Create all tables. Used in tests and SQLite dev mode only.
    In production alembic upgrade head handles schema management."""
    from app.db.base import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
