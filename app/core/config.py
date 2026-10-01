from __future__ import annotations

from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    # --- General app metadata -------------------------------------------------
    PROJECT_NAME: str = "Order & Inventory Service"
    VERSION: str = "0.1.0"
    ENVIRONMENT: str = "local"  # "local" | "staging" | "production"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    API_V1_PREFIX: str = "/api/v1"

    DATABASE_URL: str = "postgresql://postgres:postgres@db:5432/order_and_inventory_db"
    SYNC_DATABASE_URL: str = "postgresql+psycopg://postgres:postgres@db:5432/order_and_inventory_db"
    DB_POOL_MIN_SIZE: int = 2
    DB_POOL_MAX_SIZE: int = 10
    DB_COMMAND_TIMEOUT: float = 10.0

    REDIS_URL: str = "redis://localhost:6379/0"
    PRODUCT_CACHE_TTL_SECONDS: int = 300
    PRODUCT_LIST_CACHE_TTL_SECONDS: int = 60
    ORDER_CACHE_TTL_SECONDS: int = 60

    JWT_SECRET: str = "Change-Me-In-Production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    ORDER_EXPIRE_MINUTES: int = 15
    IDEMPOTENCY_KEY_TTL_HOURS: int = 24

    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    CORS_ORIGINS: Annotated[list[str], NoDecode] = ["*"]
    ALLOWED_HOSTS: Annotated[list[str], NoDecode] = ["*"]
    RATE_LIMIT: str = "100/minute"

    RUN_SCHEDULER: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("CORS_ORIGINS", "ALLOWED_HOSTS", mode="before")
    @classmethod
    def _split_comma_separated(cls, value: object) -> object:
        "Allow `CORS_ORIGINS=https://a.com,https://b.com` style env vars instead of requiring JSON-encoded lists."
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


settings = Settings()
