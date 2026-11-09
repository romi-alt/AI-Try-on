import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.core.storage import public_url
from app.models.tryon_job import JobStatus


class TryOnCreate(BaseModel):
    session_id: uuid.UUID
    garment_id: uuid.UUID
    capture_key: str = Field(min_length=1, max_length=512)


class TryOnJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    session_id: uuid.UUID
    garment_id: uuid.UUID
    status: JobStatus
    capture_key: str
    result_key: str | None
    error: str | None
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def result_url(self) -> str | None:
        return public_url(self.result_key) if self.result_key else None
