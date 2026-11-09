import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.tryon_job import JobStatus


class JobStateOut(BaseModel):
    """Current state of a try-on job. Fields match the WebSocket messages (`job`, `status`, `pct`, ...)."""

    job: uuid.UUID
    status: JobStatus
    pct: int = Field(ge=0, le=100)
    url: str | None = Field(default=None, description="Signed result URL, present when status is done")
    error: str | None = Field(default=None, description="Shopper-readable message, present when failed")
    updated_at: datetime
