import logging
import uuid

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.api.deps import AsyncDb
from app.core.auth import require_admin
from app.core.redis import get_redis
from app.core.storage import capture_key_belongs_to, object_exists
from app.models import JobStatus, KioskSession, Product, TryOnJob
from app.schemas.tryon import TryOnAccepted, TryOnCreate, TryOnJobOut
from app.services.job_state import job_channel, write_state
from app.services.queue import enqueue_tryon

router = APIRouter(prefix="/tryon", tags=["tryon"])
logger = logging.getLogger("app.tryon")


@router.post("", response_model=TryOnAccepted, status_code=status.HTTP_202_ACCEPTED)
async def create_tryon(payload: TryOnCreate, db: AsyncDb):
    """Queue a try-on and return immediately.

    Follow progress by subscribing to the Redis channel in the response, or by polling
    `GET /tryon/{job_id}`.
    """
    if not await db.get(KioskSession, payload.session_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")

    # The same product twice in one outfit is meaningless; keep first occurrence, preserve order.
    product_ids = list(dict.fromkeys(payload.product_ids))
    found = set(await db.scalars(select(Product.id).where(Product.id.in_(product_ids))))
    if missing := [str(p) for p in product_ids if p not in found]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Products not found: {', '.join(missing)}")

    recommended = list(dict.fromkeys(payload.recommended_product_ids))
    if stray := [str(p) for p in recommended if p not in product_ids]:
        raise HTTPException(422, f"recommended_product_ids must be part of product_ids: {', '.join(stray)}")

    # The key must be one /capture issued to *this* session: sessions cannot use each other's photos.
    if not capture_key_belongs_to(payload.capture_key, payload.session_id):
        raise HTTPException(422, "capture_key does not belong to this session")
    try:
        exists = await run_in_threadpool(object_exists, payload.capture_key)
    except (BotoCoreError, ClientError) as e:
        logger.exception("capture_lookup_failed", extra={"session_id": str(payload.session_id)})
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Storage is unavailable. Try again.") from e
    if not exists:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Capture not found. Photos expire after an hour; take a new one."
        )

    job = TryOnJob(
        session_id=payload.session_id,
        product_ids=product_ids,
        recommended_product_ids=recommended,
        person_image_key=payload.capture_key,
    )
    db.add(job)
    await db.commit()  # committed before enqueueing so the worker can always find the row
    await db.refresh(job)

    try:
        await run_in_threadpool(enqueue_tryon, job.id, job.session_id)
    except Exception as e:
        logger.exception("tryon_enqueue_failed", extra={"job_id": str(job.id)})
        job.status = JobStatus.failed
        job.error = "The try-on service is busy. Please try again in a moment."
        await db.commit()
        _announce_failure(job)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, job.error) from e

    logger.info(
        "tryon_queued",
        extra={"job_id": str(job.id), "session_id": str(job.session_id), "products": len(product_ids)},
    )
    return TryOnAccepted(job_id=job.id, status=job.status, channel=job_channel(job.session_id))


def _announce_failure(job: TryOnJob) -> None:
    """Best effort: tell listeners (and the state hash) the job failed. Redis may be what broke."""
    try:
        write_state(get_redis(), job.id, job.session_id, "failed", 0, error=job.error)
    except Exception:
        logger.warning("tryon_failure_announce_failed", extra={"job_id": str(job.id)})


@router.get("/{job_id}", response_model=TryOnJobOut)
async def get_tryon(job_id: uuid.UUID, db: AsyncDb):
    job = await db.get(TryOnJob, job_id)
    if not job:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return job


@router.get("", response_model=list[TryOnJobOut], dependencies=[Depends(require_admin)])
async def list_tryons(db: AsyncDb, limit: int = Query(50, ge=1, le=500)):
    result = await db.scalars(select(TryOnJob).order_by(TryOnJob.created_at.desc()).limit(limit))
    return result.all()
