from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "tryon-api"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://tryon:tryon_dev_password@localhost:5432/tryon"
    redis_url: str = "redis://localhost:6379/0"
    # RQ queue the worker consumes. Must match the worker's TRYON_QUEUE_NAME.
    tryon_queue_name: str = "tryon"
    tryon_job_timeout_seconds: int = 300
    # How long the latest state of a job (Redis hash `job:{id}`) is kept after its last update.
    job_state_ttl_seconds: int = 24 * 3600

    # --- WebSocket /ws ---
    ws_heartbeat_seconds: float = 25.0
    ws_subscribe_timeout_seconds: float = 5.0

    s3_endpoint_url: str = "http://localhost:9000"
    # Endpoint embedded in presigned URLs handed to the browser (host-reachable).
    s3_presign_endpoint_url: str | None = None
    s3_region: str = "auto"
    s3_bucket: str = "tryon-media"
    s3_access_key_id: str = "minioadmin"
    s3_secret_access_key: str = "minioadmin_dev_password"
    s3_public_base_url: str = "http://localhost:9000/tryon-media"
    presign_expires_seconds: int = 600
    # Garment images go straight to the bucket (a presigned PUT cannot cap the size), so the size is
    # checked afterwards: by POST /uploads/verify, and by the sweeper for uploads nobody verified.
    # Keep this at or above the admin app's own limit (10 MB) so its pre-check never disagrees.
    garment_max_bytes: int = 10 * 1024 * 1024

    # --- webcam captures (POST /capture) ---
    capture_max_bytes: int = 5 * 1024 * 1024
    capture_min_height: int = 768
    # Decoded-pixel ceiling, checked from the header before decoding (decompression-bomb guard).
    capture_max_pixels: int = 40_000_000
    # Captures are personal photos: deleted after this long.
    capture_ttl_seconds: int = 3600
    capture_cleanup_enabled: bool = True
    capture_cleanup_interval_seconds: int = 300

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
