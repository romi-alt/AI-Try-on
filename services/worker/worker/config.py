from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://tryon:tryon_dev_password@localhost:5432/tryon"
    redis_url: str = "redis://localhost:6379/0"
    # Must match the API's TRYON_QUEUE_NAME.
    tryon_queue_name: str = "tryon"
    job_timeout_seconds: int = 300
    # How long the latest state of a job (Redis hash `job:{id}`) is kept after its last update.
    job_state_ttl_seconds: int = 24 * 3600

    # S3-compatible storage: MinIO locally, Cloudflare R2 in production.
    s3_endpoint_url: str = "http://localhost:9000"
    # Host-visible endpoint baked into the presigned result URL (browsers can't reach `minio:9000`).
    s3_presign_endpoint_url: str | None = None
    s3_region: str = "auto"
    s3_bucket: str = "tryon-media"
    s3_access_key_id: str = "minioadmin"
    s3_secret_access_key: str = "minioadmin_dev_password"
    s3_public_base_url: str = "http://localhost:9000/tryon-media"
    result_url_expires_seconds: int = 3600

    # --- asset jobs (embeddings, background removal): a separate queue and worker, so heavy CPU/GPU work
    # never
    # delays a shopper's try-on. Must match the API's ASSETS_QUEUE_NAME.
    assets_queue_name: str = "assets"
    assets_job_timeout_seconds: int = 900
    # Which queues this process consumes, comma separated: "tryon" (default) or "assets".
    worker_queues: str = "tryon"

    # FashionCLIP (CLIP fine-tuned on fashion product images; 512-d image embeddings).
    fashion_clip_model: str = "patrickjohncyh/fashion-clip"
    embedding_batch_size: int = 8

    # Background removal (rembg) and mask refinement (SAM 2).
    rembg_model: str = "isnet-general-use"
    sam2_checkpoint: str = ""  # path to a SAM 2.1 checkpoint, e.g. sam2.1_hiera_tiny.pt; empty disables SAM 2
    sam2_config: str = "configs/sam2.1/sam2.1_hiera_t.yaml"
    garment_max_side: int = 2048  # larger uploads are scaled down before processing
    models_dir: str = "~/.cache/tryon-models"

    # --- provider selection ---
    tryon_provider: Literal["mock", "fashn"] = "mock"

    mock_duration_seconds: float = 8.0
    mock_steps: int = 8
    mock_fail: bool = False  # force the failure path, for developing the kiosk's error UI

    fashn_api_key: str | None = None  # never commit a real key; set it in the environment
    fashn_base_url: str = "https://api.fashn.ai/v1"
    fashn_model_name: str = "tryon-v1.6"
    fashn_mode: Literal["performance", "balanced", "quality"] = "balanced"
    fashn_poll_interval_seconds: float = 3.0
    fashn_timeout_seconds: float = 180.0  # per garment

    @property
    def presign_endpoint(self) -> str:
        return self.s3_presign_endpoint_url or self.s3_endpoint_url


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
