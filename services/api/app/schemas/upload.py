from typing import Literal

from pydantic import BaseModel


class PresignRequest(BaseModel):
    content_type: Literal["image/jpeg", "image/png", "image/webp"]
    kind: Literal["capture", "garment"] = "capture"


class PresignResponse(BaseModel):
    key: str
    upload_url: str
    public_url: str
    expires_in: int
