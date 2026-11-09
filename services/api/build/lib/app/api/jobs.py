import logging
import uuid
from datetime import datetime

import redis
from fastapi import APIRouter, HTTPException, Response, status
from starlette.concurrency import run_in_threadpool

from app.api.deps import AsyncDb
from app.models import TryOnJob
from app.schemas.job import JobStateOut
from app.services.job_state import read_state

router = APIRouter(tags=["jobs"])
logger = logging.getLogger("app.jobs")


def _from_redis(job_id: uuid.UUID, raw: dict) -> JobStateOut | None:
    try:
        return JobStateOut(
            job=job_id,
            status=raw["status"],
            pct=int(raw["pct"]),
            url=raw.get("url"),
            error=raw.get("error"),
            updated_at=datetime.fromisoformat(raw["updated_at"]),
        )
    except (KeyError, ValueError):
        logger.warning("job_state_corrupt", extra={"job_id": str(job_id)})
        return None


def _from_row(job: TryOnJob) -> JobStateOut:
    return JobStateOut(
        job=job.id,
        status=job.status,
        pct=job.progress,
        url=job.result_url,
        error=job.error,
        updated_at=job.updated_at,
    )


@router.get("/jobs/{job_id}", response_model=JobStateOut)
async def get_job(job_id: uuid.UUID, response: Response, db: AsyncDb):
    """Where a try-on job is right now: the polling fallback, and the first call after a reconnect.

    Read from the Redis hash the worker keeps up to date. If it is missing (expired, or Redis restarted) or
    Redis is unreachable, the answer comes from Postgres instead.
    """
    response.headers["Cache-Control"] = "no-store"

    try:
        raw = await run_in_threadpool(read_state, job_id)
    except redis.RedisError:
        logger.warning("job_state_redis_unavailable", extra={"job_id": str(job_id)})
        raw = None
    if raw and (state := _from_redis(job_id, raw)):
        return state

    job = await db.get(TryOnJob, job_id)
    if not job:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return _from_row(job)
