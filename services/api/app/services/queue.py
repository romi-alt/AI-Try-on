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
from app.core.redis import get_rq_redis

JOB_FUNCTION = "worker.tasks.run_tryon_job"
FAILURE_CALLBACK = "worker.tasks.handle_rq_failure"
FAILED_JOB_RETENTION_SECONDS = 24 * 3600


def get_queue() -> Queue:
    return Queue(settings.tryon_queue_name, connection=get_rq_redis(), serializer=JSONSerializer)


def job_channel(session_id: uuid.UUID | str) -> str:
    return f"session:{session_id}:job"


def enqueue_tryon(job_id: uuid.UUID) -> None:
    get_queue().enqueue(
        JOB_FUNCTION,
        str(job_id),
        job_id=str(job_id),
        job_timeout=settings.tryon_job_timeout_seconds,
        result_ttl=0,  # the result lives in Postgres and R2, not in RQ
        failure_ttl=FAILED_JOB_RETENTION_SECONDS,
        on_failure=Callback(FAILURE_CALLBACK),
    )


def queue_depth() -> int:
    return len(get_queue())
