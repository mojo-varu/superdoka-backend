from typing import Optional

from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    ENVIRONMENT: str = "DEV"
    DATABASE_URL: str = "postgresql+asyncpg://postgres:jumbo@db:5432/tagaada"
    TEST_DATABASE_URL: str = "postgresql+asyncpg://postgres:jumbo@db:5432/tagaada_test"
    # SPEC-016-R03: never hard-code a token. Unused elsewhere in the codebase
    # (verified: only this declaration references it) — the new bot channel
    # reads TELEGRAM_BOT_TOKEN_DEV/_PROD via app/channels/settings.py instead.
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    S3_BUCKET: str = ""
    GROUP_MESSAGE_SECRET_KEY: str = "your-secret-key-change-in-env"
    
    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()