"""Try-on worker: BLPOP jobs from Redis and render them.

Contract (see services/api/app/services/queue.py): payload is JSON
{"job_id": "<uuid>", "version": 1}. Job state lives in Postgres.
"""

import json
import logging
import signal
import uuid

import redis

from worker import db
from worker.config import settings
from worker.pipeline import process_job

logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("worker")

_running = True


def _stop(signum, _frame) -> None:
    global _running
    log.info("received signal %s; finishing current job then exiting", signum)
    _running = False


def main() -> None:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    db.ping()
    r = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    r.ping()
    log.info("worker up; provider=%s queue=%s", settings.tryon_provider, settings.tryon_queue_key)

    while _running:
        item = r.blpop(settings.tryon_queue_key, timeout=settings.poll_block_seconds)
        if item is None:
            continue
        _, raw = item
        try:
            payload = json.loads(raw)
            job_id = uuid.UUID(payload["job_id"])
        except (ValueError, KeyError, TypeError):
            log.error("malformed queue payload: %r", raw)
            continue
        process_job(job_id)

    log.info("worker stopped")


if __name__ == "__main__":
    main()
