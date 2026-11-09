import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.staff_request import StaffRequestStatus


class StaffRequestCreate(BaseModel):
    session_id: uuid.UUID
    product_id: uuid.UUID
    size: str | None = Field(default=None, max_length=20)
    color: str | None = Field(default=None, max_length=40)


class StaffRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    session_id: uuid.UUID
    product_id: uuid.UUID
    product_name: str
    size: str | None
    color: str | None
    status: StaffRequestStatus
    created_at: datetime
    updated_at: datetime


class StaffRequestStatusIn(BaseModel):
    status: Literal["bringing", "done"]
