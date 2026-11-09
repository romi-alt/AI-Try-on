import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SessionCreate(BaseModel):
    consent_given: bool = False


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    started_at: datetime
    consent_given: bool


class SessionAdminOut(SessionOut):
    job_count: int = 0
