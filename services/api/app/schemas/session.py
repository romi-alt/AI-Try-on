import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator


class SessionCreate(BaseModel):
    # Required (no default): the shopper must explicitly consent to webcam capture.
    # StrictBool: only a JSON true counts. "yes" or 1 would be coerced by default; consent must be explicit.
    consent_given: StrictBool = Field(description="Must be true; a session cannot start without consent.")

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
