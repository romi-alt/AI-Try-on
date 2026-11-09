"""Job queue contract shared with services/worker.

Queue: a Redis list at `settings.tryon_queue_key`. API RPUSHes a JSON payload,
worker BLPOPs it. Progress/status lives in Postgres (tryon_jobs); Redis is only
transport, so a lost message can be re-enqueued from the DB.
"""

import json
import uuid

from app.core.config import settings
from app.core.redis import get_redis


def enqueue_tryon(job_id: uuid.UUID) -> None:
    payload = json.dumps({"job_id": str(job_id), "version": 1})
    get_redis().rpush(settings.tryon_queue_key, payload)


def queue_depth() -> int:
    return int(get_redis().llen(settings.tryon_queue_key))
