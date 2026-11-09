import logging
import time
import uuid

from worker import db, storage
from worker.providers import get_provider
from worker.providers.base import TryOnInput

log = logging.getLogger("worker.pipeline")


def process_job(job_id: uuid.UUID) -> None:
    provider = get_provider()
    job = db.fetch_job(job_id)
    if job is None:
        log.warning("job %s not found; dropping", job_id)
        return
    if not db.mark_processing(job_id, provider.name):
        log.info("job %s already claimed (status=%s); skipping", job_id, job.status)
        return

    started = time.monotonic()
    try:
        person = storage.get_bytes(job.capture_key)
        garment = storage.get_bytes(job.garment_image_key)

        result = provider.run(
            TryOnInput(person_image=person, garment_image=garment, garment_category=job.garment_category)
        )

        ext = "png" if result.content_type == "image/png" else "jpg"
        result_key = f"result/{job_id}.{ext}"
        storage.put_bytes(result_key, result.image, result.content_type)

        duration_ms = int((time.monotonic() - started) * 1000)
        db.mark_done(job_id, result_key, duration_ms)
        log.info("job %s done in %dms via %s", job_id, duration_ms, provider.name)
    except Exception as e:
        duration_ms = int((time.monotonic() - started) * 1000)
        log.exception("job %s failed", job_id)
        db.mark_failed(job_id, f"{e.__class__.__name__}: {e}", duration_ms)
