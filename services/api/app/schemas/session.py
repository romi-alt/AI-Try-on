import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SessionCreate(BaseModel):
    kiosk_id: str = Field(min_length=1, max_length=120)


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kiosk_id: str
    started_at: datetime
    ended_at: datetime | None


class SessionAdminOut(SessionOut):
    job_count: int = 0
