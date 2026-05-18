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

    # Twilio — optional; services degrade gracefully when unset.
    TWILIO_ACCOUNT_SID: str | None = None
    TWILIO_AUTH_TOKEN: str | None = None
    TWILIO_FROM_NUMBER: str | None = None
    TWILIO_TWIML_APP_SID: str | None = None
    TWILIO_API_KEY_SID: str | None = None
    TWILIO_API_KEY_SECRET: str | None = None

    # Resend — optional; emails are mocked in development when unset.
    RESEND_API_KEY: str | None = None
    RESEND_WEBHOOK_SECRET: str | None = None
    RESEND_FROM_EMAIL: str | None = None

    # SLA defaults — applied to new inbound threads.
    SLA_FIRST_RESPONSE_MINUTES: int = 60
    SLA_RESOLUTION_MINUTES: int = 480

    # Anthropic — optional; agents degrade to a mock response when unset.
    ANTHROPIC_API_KEY: str | None = None

    # ARQ background worker.
    WORKER_MAX_JOBS: int = 10
    WORKER_JOB_TIMEOUT: int = 120

    # PostHog — server-side webhook ingestion.
    POSTHOG_WEBHOOK_SECRET: str | None = None

    # Attribution / website integration.
    API_BASE_URL: str = "http://localhost:8000"
    TRACKING_RATE_LIMIT_PER_MINUTE: int = 100


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor — settings are immutable for the process lifetime."""
    return Settings()


settings = get_settings()
