import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.tryon_job import JobStatus

MAX_PRODUCTS_PER_JOB = 5


class TryOnCreate(BaseModel):
    session_id: uuid.UUID
    product_ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_PRODUCTS_PER_JOB)
    person_image_key: str = Field(min_length=1, max_length=512)


class TryOnJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    session_id: uuid.UUID
    product_ids: list[uuid.UUID]
    status: JobStatus
    progress: int
    person_image_key: str
    result_url: str | None
    error: str | None
    created_at: datetime
    updated_at: datetime
