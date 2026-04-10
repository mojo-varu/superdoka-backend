# app/init_db.py
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from app.db.base import Base
from app.config import settings
import logging

logger = logging.getLogger(__name__)

async def init_database():
    """Initialize database tables"""
    try:
        # Create async engine
        engine = create_async_engine(settings.DATABASE_URL, echo=True)
        
        # Create all tables
        async with engine.begin() as conn:
            # Drop all tables (be careful in production!)
            await conn.run_sync(Base.metadata.drop_all)
            
            # Create all tables
            await conn.run_sync(Base.metadata.create_all)
        
        await engine.dispose()
        logger.info("✅ Database tables created successfully")
        
    except Exception as e:
        logger.error(f"❌ Failed to initialize database: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(init_database())