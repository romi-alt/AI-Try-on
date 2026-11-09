from pydantic import BaseModel


class CaptureOut(BaseModel):
    key: str
    width: int
    height: int
    content_type: str = "image/webp"
    size_bytes: int
    expires_in_seconds: int
