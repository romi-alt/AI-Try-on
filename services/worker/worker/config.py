from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://tryon:tryon_dev_password@localhost:5432/tryon"
    redis_url: str = "redis://localhost:6379/0"
    tryon_queue_key: str = "tryon:jobs"

    s3_endpoint_url: str = "http://localhost:9000"
    s3_region: str = "auto"
    s3_bucket: str = "tryon-media"
    s3_access_key_id: str = "minioadmin"
    s3_secret_access_key: str = "minioadmin_dev_password"

    tryon_provider: str = "stub"
    replicate_api_token: str | None = None
    replicate_model: str | None = None

    job_timeout_seconds: int = 120
    poll_block_seconds: int = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
