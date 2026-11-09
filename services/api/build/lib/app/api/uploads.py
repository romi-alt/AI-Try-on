import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.auth import require_admin
from app.core.config import settings
from app.core.storage import (
    build_key,
    delete_object,
    expected_content_type,
    is_garment_key,
    object_info,
    presigned_put,
    public_url,
)
from app.schemas.upload import PresignRequest, PresignResponse, VerifyRequest, VerifyResponse


def _human_size(n: int) -> str:
    mb = 1024 * 1024
    if n >= mb:
        return f"{n // mb} MB" if n % mb == 0 else f"{n / mb:.1f} MB"
    return f"{max(n // 1024, 1)} KB"


router = APIRouter(prefix="/uploads", tags=["uploads"], dependencies=[Depends(require_admin)])
logger = logging.getLogger("app.uploads")


@router.post("/presign", response_model=PresignResponse)
def presign(payload: PresignRequest):
    """Hand the admin app a short-lived PUT URL so image bytes never transit the API. Admin only."""
    key = build_key(payload.kind, payload.content_type)
    return PresignResponse(
        key=key,
        upload_url=presigned_put(key, payload.content_type),
        public_url=public_url(key),
        expires_in=settings.presign_expires_seconds,
    )


@router.post("/verify", response_model=VerifyResponse)
def verify(payload: VerifyRequest):
    """Check an upload after the browser has PUT it, and delete it if it is not acceptable.

    A presigned PUT URL cannot limit the size, so this is where the limit is enforced: an object larger than
    `GARMENT_MAX_BYTES`, or stored under a different content type than its key says, is deleted and refused.
    Only keys that `/uploads/presign` hands out are accepted, so this cannot be pointed at other objects.
    """
    key = payload.key
    if not is_garment_key(key):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Not a garment upload key")
    info = object_info(key)
    if info is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nothing was uploaded under that key")

    problem = None
    code = status.HTTP_422_UNPROCESSABLE_ENTITY
    if info["size"] > settings.garment_max_bytes:
        code = 413
        problem = f"That image is larger than {_human_size(settings.garment_max_bytes)}"
    elif info["size"] <= 0:
        problem = "The uploaded file is empty"
    elif info["content_type"] != expected_content_type(key):
        problem = "The uploaded file has the wrong content type"
    if problem:
        delete_object(key)
        logger.warning("garment_upload_rejected", extra={"key": key, "size": info["size"], "reason": problem})
        raise HTTPException(code, problem)

    return VerifyResponse(
        key=key, size_bytes=info["size"], content_type=info["content_type"], public_url=public_url(key)
    )
