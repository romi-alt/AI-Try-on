from typing import Literal

from pydantic import BaseModel


class PresignRequest(BaseModel):
    content_type: Literal["image/jpeg", "image/png", "image/webp"]
    # Webcam captures go through POST /capture (validated and sanitised), never direct to storage.
    kind: Literal["garment"] = "garment"


class PresignResponse(BaseModel):
    key: str
    upload_url: str
    public_url: str
    expires_in: int


class VerifyRequest(BaseModel):
    key: str


class VerifyResponse(BaseModel):
    key: str
    size_bytes: int
    content_type: str
    public_url: str
