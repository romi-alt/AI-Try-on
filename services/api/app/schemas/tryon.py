import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.tryon_job import JobStatus

MAX_PRODUCTS_PER_JOB = 5


class TryOnCreate(BaseModel):
    session_id: uuid.UUID
    capture_key: str = Field(
        min_length=1, max_length=512, description="Key returned by POST /capture for this session"
    )
    product_ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_PRODUCTS_PER_JOB)


class TryOnAccepted(BaseModel):
    job_id: uuid.UUID
    status: JobStatus
    channel: str = Field(description="Redis pub/sub channel carrying {job, status, pct} updates")


class TryOnJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    session_id: uuid.UUID
    product_ids: list[uuid.UUID]
    status: JobStatus
    progress: int
    capture_key: str = Field(validation_alias="person_image_key")
    result_url: str | None
    error: str | None
    created_at: datetime
    updated_at: datetime
