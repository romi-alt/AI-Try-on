from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "tryon-api"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://tryon:tryon_dev_password@localhost:5432/tryon"
    redis_url: str = "redis://localhost:6379/0"
    tryon_queue_key: str = "tryon:jobs"

    s3_endpoint_url: str = "http://localhost:9000"
    # Endpoint embedded in presigned URLs handed to the browser (host-reachable).
    s3_presign_endpoint_url: str | None = None
    s3_region: str = "auto"
    s3_bucket: str = "tryon-media"
    s3_access_key_id: str = "minioadmin"
    s3_secret_access_key: str = "minioadmin_dev_password"
    s3_public_base_url: str = "http://localhost:9000/tryon-media"
    presign_expires_seconds: int = 600

    api_cors_origins: str = "http://localhost:3000,http://localhost:3001"
    admin_api_key: str = Field(default="dev-admin-key", description="Dev-only shared secret")

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.api_cors_origins.split(",") if o.strip()]

    @property
    def presign_endpoint(self) -> str:
        return self.s3_presign_endpoint_url or self.s3_endpoint_url


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
