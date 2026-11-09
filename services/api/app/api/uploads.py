from fastapi import APIRouter

from app.core.config import settings
from app.core.storage import build_key, presigned_put, public_url
from app.schemas.upload import PresignRequest, PresignResponse

router = APIRouter(prefix="/uploads", tags=["uploads"])


@router.post("/presign", response_model=PresignResponse)
def presign(payload: PresignRequest):
    """Hand the browser a short-lived PUT URL so image bytes never transit the API."""
    key = build_key(payload.kind, payload.content_type)
    return PresignResponse(
        key=key,
        upload_url=presigned_put(key, payload.content_type),
        public_url=public_url(key),
        expires_in=settings.presign_expires_seconds,
    )
