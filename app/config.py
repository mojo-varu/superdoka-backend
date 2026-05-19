from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    ENVIRONMENT: str = "DEV"
    DATABASE_URL: str = "postgresql+asyncpg://postgres:jumbo@db:5432/tagaada"
    TEST_DATABASE_URL: str = "postgresql+asyncpg://postgres:jumbo@db:5432/tagaada_test"
    TELEGRAM_BOT_TOKEN: str ="7499510946:AAHMFBskAAItdWrbs7o52sVj6vFd8hyeuOQ"
    S3_BUCKET: str = ""
    GROUP_MESSAGE_SECRET_KEY: str = "your-secret-key-change-in-env"
    
    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()