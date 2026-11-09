"""Try-on job queue (RQ) shared with services/worker.

The API enqueues by dotted path, so it never imports the worker package. Payloads use RQ's JSON
serializer (not pickle), and the RQ job id is the `tryon_jobs.id`, which ties the two together.
Job state lives in Postgres; progress is published on Redis pub/sub channel
`session:{session_id}:job` by the worker.
"""

import uuid

from rq import Callback, Queue
from rq.serializers import JSONSerializer

from app.core.config import settings
from app.core.redis import get_redis, get_rq_redis
from app.services.job_state import write_state

JOB_FUNCTION = "worker.tasks.run_tryon_job"
FAILURE_CALLBACK = "worker.tasks.handle_rq_failure"
FAILED_JOB_RETENTION_SECONDS = 24 * 3600


def get_queue() -> Queue:
    return Queue(settings.tryon_queue_name, connection=get_rq_redis(), serializer=JSONSerializer)


def enqueue_tryon(job_id: uuid.UUID, session_id: uuid.UUID) -> None:
    """Record the job as queued (hash + pub/sub), then hand it to the worker.

    The state is written first: once the job is on the queue the worker owns it and may update the
    hash at any moment, so a later write here could overwrite its progress.
    """
    write_state(get_redis(), job_id, session_id, "queued", 0)
    get_queue().enqueue(
        JOB_FUNCTION,
        str(job_id),
        job_id=str(job_id),
        job_timeout=settings.tryon_job_timeout_seconds,
        result_ttl=0,  # the result lives in Postgres and R2, not in RQ
        failure_ttl=FAILED_JOB_RETENTION_SECONDS,
        on_failure=Callback(FAILURE_CALLBACK),
    )


PROCESS_GARMENT_FUNCTION = "worker.asset_tasks.process_garment_job"
EMBED_PRODUCTS_FUNCTION = "worker.asset_tasks.embed_products_job"
ASSET_RESULT_TTL_SECONDS = 3600


def get_assets_queue() -> Queue:
    return Queue(settings.assets_queue_name, connection=get_rq_redis(), serializer=JSONSerializer)


def enqueue_process_garment(product_id: uuid.UUID, *, reembed: bool = True) -> str:
    """Queue background removal + mask generation (+ a fresh embedding) for one product. Returns the RQ
    job id."""
    job = get_assets_queue().enqueue(
        PROCESS_GARMENT_FUNCTION,
        str(product_id),
        reembed,
        job_timeout=settings.assets_job_timeout_seconds,
        result_ttl=ASSET_RESULT_TTL_SECONDS,
        failure_ttl=FAILED_JOB_RETENTION_SECONDS,
    )
    return job.id


def enqueue_embeddings(product_ids: list[uuid.UUID] | None, *, only_missing: bool = False) -> str:
    """Queue (re)computing FashionCLIP embeddings: for `product_ids`, or the whole catalog when None."""
    job = get_assets_queue().enqueue(
        EMBED_PRODUCTS_FUNCTION,
        [str(p) for p in product_ids] if product_ids else None,
        only_missing,
        job_timeout=settings.assets_job_timeout_seconds,
        result_ttl=ASSET_RESULT_TTL_SECONDS,
        failure_ttl=FAILED_JOB_RETENTION_SECONDS,
    )
    return job.id


def queue_depth() -> int:
    return len(get_queue())
