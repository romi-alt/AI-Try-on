import logging
import uuid
from typing import Annotated

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from starlette.concurrency import run_in_threadpool

from app.api.deps import AsyncDb
from app.core.config import settings
from app.core.storage import capture_key, put_capture
from app.models import KioskSession
from app.schemas.capture import CaptureOut
from app.services.image_processing import CaptureRejected, process_capture

router = APIRouter(tags=["capture"])
logger = logging.getLogger("app.capture")


@router.post("/capture", response_model=CaptureOut, status_code=status.HTTP_201_CREATED)
async def upload_capture(
    db: AsyncDb,
    session_id: Annotated[uuid.UUID, Form()],
    file: Annotated[UploadFile, File(description="JPEG or WebP, portrait, at least 768px tall, max 5 MB")],
) -> CaptureOut:
    """Validate, sanitise (EXIF stripped, re-encoded as WebP) and store a webcam photo.

    Returns the object key to pass to `POST /tryon`. The photo is deleted after one hour.
    """
    if not await db.get(KioskSession, session_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")

    data = await file.read(settings.capture_max_bytes + 1)
    if len(data) > settings.capture_max_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"Image is larger than {settings.capture_max_bytes // (1024 * 1024)} MB.",
        )
    if not data:
        raise HTTPException(422, "The uploaded file is empty.")

    try:
        processed = await run_in_threadpool(process_capture, data)
    except CaptureRejected as e:
        raise HTTPException(e.status_code, e.message) from e

    key = capture_key(session_id)
    try:
        await run_in_threadpool(put_capture, key, processed.data, session_id)
    except (BotoCoreError, ClientError) as e:
        logger.exception("capture_store_failed", extra={"session_id": str(session_id)})
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Could not store the photo. Try again."
        ) from e

    logger.info(
        "capture_stored",
        extra={
            "session_id": str(session_id),
            "key": key,
            "width": processed.width,
            "height": processed.height,
            "bytes_in": len(data),
            "bytes_stored": len(processed.data),
        },
    )
    return CaptureOut(
        key=key,
        width=processed.width,
        height=processed.height,
        size_bytes=len(processed.data),
        expires_in_seconds=settings.capture_ttl_seconds,
    )
