from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_port: int = 8080
    order_expiry_seconds: int = 900
    expiry_scan_interval_seconds: int = 30

    jwt_secret: str = "super-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "marketplace"
    postgres_user: str = "marketplace"
    postgres_password: str = "marketplace"

    redis_host: str = "redis"
    redis_port: int = 6379
    redis_db: int = 0
    product_cache_ttl_seconds: int = 300
    idempotency_cache_ttl_seconds: int = 86400

    @property
    def database_url(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
