import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SessionCreate(BaseModel):
    # Required (no default): the shopper must explicitly consent to webcam capture.
    consent_given: bool = Field(description="Must be true; a session cannot start without consent.")

    @field_validator("consent_given")
    @classmethod
    def _must_consent(cls, v: bool) -> bool:
        if v is not True:
            raise ValueError("consent_given must be true to start a session")
        return v


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    started_at: datetime
    consent_given: bool


class SessionAdminOut(SessionOut):
    job_count: int = 0
