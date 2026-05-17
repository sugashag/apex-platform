"""Application configuration sourced from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed settings loaded from environment variables / `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Application
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    VERSION: str = "0.1.0"

    # Database
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://apex:apex@localhost:5432/apex",
        description="Async SQLAlchemy URL (must use asyncpg driver).",
    )
    DATABASE_URL_SYNC: str = Field(
        default="postgresql+psycopg://apex:apex@localhost:5432/apex",
        description="Sync URL used by Alembic.",
    )

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Auth
    SECRET_KEY: str = Field(
        default="change-me-to-a-long-random-string",
        description="Secret used to sign JWT access tokens.",
    )
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor — settings are immutable for the process lifetime."""
    return Settings()


settings = get_settings()
