"""The RQ job: render one try-on and report on it.

`run_tryon_job` is what the API enqueues (by dotted path). It never raises for an expected failure:
it records `failed` with a shopper-readable message in Postgres and on the Redis channel, then
returns. `handle_rq_failure` is RQ's safety net for the cases it cannot catch (the process was
killed, the DB was down while recording a failure).
"""

import io
import logging
import time
import uuid
from datetime import UTC, datetime, timedelta

import redis
from botocore.exceptions import BotoCoreError, ClientError
from PIL import Image
from rq.timeouts import JobTimeoutException

from worker import analytics, db, storage
from worker.config import settings
from worker.events import JobEvents
from worker.providers import ProviderError, get_provider
from worker.providers.base import GarmentInput, TryOnRequest

logger = logging.getLogger("worker.tasks")

GENERIC_ERROR = "Something went wrong while creating your try-on. Please try again."
TIMEOUT_ERROR = "Creating your try-on took too long. Please try again."
CAPTURE_GONE = "Your photo is no longer available (photos are deleted after an hour). Please take a new one."
PRODUCT_GONE = "One of the selected items is no longer available."
STORAGE_ERROR = "We couldn't reach photo storage. Please try again in a moment."

# Share of the progress bar given to each stage. The provider owns the stretch in the middle.
LOADED_PCT = 5
PROVIDER_START, PROVIDER_END = 10, 90
ENCODED_PCT = 92
UPLOADED_PCT = 97


class JobFailure(Exception):
    """An expected failure carrying a message that is safe to show the shopper."""


class _Progress:
    """Writes each step to Postgres, then publishes it. Only ever moves forward."""

    def __init__(self, job_id: uuid.UUID, events: JobEvents):
        self.job_id = job_id
        self.events = events
        self.last = -1

    def update(self, pct: int) -> None:
        pct = max(0, min(99, int(pct)))  # 100 is reserved for "done"
        if pct <= self.last:
            return
        self.last = pct
        db.set_progress(self.job_id, pct)
        self.events.processing(pct)


def run_tryon_job(job_id: str) -> None:
    jid = uuid.UUID(job_id)
    job = db.fetch_job(jid)
    if job is None:
        logger.warning("job_not_found", extra={"job_id": job_id})
        return
    if not db.claim_job(jid):
        logger.info("job_already_claimed", extra={"job_id": job_id, "status": job.status})
        return

    conn = redis.Redis.from_url(settings.redis_url)
    events = JobEvents(conn, jid, job.session_id)
    progress = _Progress(jid, events)
    started = time.monotonic()
    try:
        progress.update(0)
        result_url = _render(job, progress)
    except JobTimeoutException:
        _fail(jid, events, progress, TIMEOUT_ERROR, "job timed out")
    except JobFailure as e:
        _fail(jid, events, progress, str(e), None)
    except ProviderError as e:
        _fail(jid, events, progress, e.message, e.detail)
    except Exception:
        logger.exception("job_crashed", extra={"job_id": job_id})
        _fail(jid, events, progress, GENERIC_ERROR, None, log=False)
    else:
        db.mark_done(jid, result_url)
        events.done(result_url)
        render_seconds = round(time.monotonic() - started, 2)
        logger.info(
            "job_done",
            extra={"job_id": job_id, "session_id": str(job.session_id), "seconds": render_seconds},
        )
        analytics.track(
            "tryon_done",
            job.session_id,
            product_count=len(job.product_ids),
            recommended_count=len(job.recommended_product_ids),
            render_seconds=render_seconds,
            # from the shopper tapping "Try it on" to the look being ready, queue time included
            total_seconds=_since(job.created_at, render_seconds),
            provider=settings.tryon_provider,
        )
    finally:
        conn.close()


def _since(created_at, fallback: float) -> float:
    """Seconds since the job row was made, or `fallback` when the row has no timestamp."""
    if created_at is None:
        return fallback
    now = datetime.now(created_at.tzinfo or UTC)
    return round(max(fallback, (now - created_at).total_seconds()), 2)


def _render(job: db.JobRow, progress: _Progress) -> str:
    provider = get_provider()

    try:
        person = storage.get_bytes(job.person_image_key)
    except storage.ObjectMissing as e:
        raise JobFailure(CAPTURE_GONE) from e
    except (BotoCoreError, ClientError) as e:
        raise JobFailure(STORAGE_ERROR) from e

    rows = db.fetch_products(job.product_ids)
    garments = []
    for product_id in job.product_ids:  # keep the order the shopper chose
        product = rows.get(product_id)
        if product is None:
            raise JobFailure(PRODUCT_GONE)
        try:
            image = storage.load_image_from_url(product.garment_image_url)
        except storage.ObjectMissing as e:
            raise JobFailure(f"The image for {product.name!r} is missing.") from e
        except Exception as e:
            raise JobFailure(f"The image for {product.name!r} could not be loaded.") from e
        garments.append(GarmentInput(product.id, product.name, product.category, image))
    progress.update(LOADED_PCT)

    span = PROVIDER_END - PROVIDER_START
    result = provider.run(
        TryOnRequest(person_image=person, garments=garments),
        on_progress=lambda pct: progress.update(PROVIDER_START + span * max(0, min(100, pct)) / 100),
    )

    webp = _to_webp(result.image)
    progress.update(ENCODED_PCT)

    key = f"results/{job.session_id}/{job.id}.webp"
    try:
        storage.put_bytes(key, webp, "image/webp")
        url = storage.presigned_get_url(key)
    except (BotoCoreError, ClientError) as e:
        raise JobFailure(STORAGE_ERROR) from e
    progress.update(UPLOADED_PCT)
    return url


def _to_webp(image: bytes) -> bytes:
    """Normalise whatever the provider returned to a metadata-free WebP."""
    try:
        img = Image.open(io.BytesIO(image))
        img.load()
    except OSError as e:
        raise ProviderError("The try-on result could not be processed.", detail=str(e)) from e
    clean = Image.new("RGB", img.size)
    clean.paste(img.convert("RGB"))
    out = io.BytesIO()
    clean.save(out, format="WEBP", quality=90)
    return out.getvalue()


def _fail(
    job_id: uuid.UUID,
    events: JobEvents,
    progress: _Progress,
    message: str,
    detail: str | None,
    *,
    log: bool = True,
) -> None:
    if log:
        logger.warning("job_failed", extra={"job_id": str(job_id), "error": message, "detail": detail})
    if db.mark_failed(job_id, message):
        events.failed(message, max(progress.last, 0))


def _fail_orphan(job_id: str, connection: redis.Redis, message: str) -> None:
    """Fail a job whose worker is gone. Does nothing if the job already finished or failed."""
    row = db.fetch_job(uuid.UUID(job_id))
    if row is None:
        return
    if db.mark_failed(row.id, message):
        JobEvents(connection, row.id, row.session_id).failed(message, row.progress)


def handle_rq_failure(job, connection, exc_type, exc_value, traceback) -> None:
    """RQ failure callback, for exceptions that escaped `run_tryon_job` (e.g. the DB was down
    while recording a failure)."""
    job_id = job.args[0]
    logger.error(
        "rq_job_failed",
        extra={
            "job_id": job_id,
            "exc_type": getattr(exc_type, "__name__", str(exc_type)),
            "exc": str(exc_value),
        },
    )
    message = TIMEOUT_ERROR if isinstance(exc_value, JobTimeoutException) else GENERIC_ERROR
    _fail_orphan(job_id, connection, message)


def handle_work_horse_killed(job, retpid, ret_val, rusage) -> None:
    """RQ calls this in the surviving parent when a job's process died outright (out-of-memory
    kill, SIGKILL). RQ does *not* run the failure callback for that, so without this the job
    would stay 'processing' forever."""
    logger.error("work_horse_killed", extra={"job_id": job.id, "exit_status": ret_val})
    _fail_orphan(job.args[0], job.connection, GENERIC_ERROR)


def reap_stale_jobs(connection: redis.Redis, *, grace_seconds: int = 60) -> int:
    """Fail jobs stuck in 'processing' because their whole worker died (nothing could catch that).

    A live job is always stopped by its own timeout, so one with no update for longer than the
    timeout plus a grace period is dead.
    """
    cutoff = timedelta(seconds=settings.job_timeout_seconds + grace_seconds)
    reaped = db.fail_stale_processing(cutoff, GENERIC_ERROR)
    for job_id, session_id, progress in reaped:
        logger.error("stale_job_reaped", extra={"job_id": str(job_id)})
        JobEvents(connection, job_id, session_id).failed(GENERIC_ERROR, progress)
    return len(reaped)
