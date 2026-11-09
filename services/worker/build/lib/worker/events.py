"""Job progress: the latest state in a Redis hash, announced on pub/sub.

Every update does two things in one MULTI/EXEC transaction:

1. replaces the hash `job:{id}` with the job's latest state (so `GET /jobs/{id}` can answer polls and
   reconnects), and
2. publishes a JSON message to `session:{session_id}:job`:

    {"job": "<job id>", "status": "processing", "pct": 40}
    {"job": "<job id>", "status": "done",       "pct": 100, "url": "https://..."}
    {"job": "<job id>", "status": "failed",     "pct": 40,  "error": "readable message"}

Because both happen together, a subscriber is never told something the hash does not show yet. A client that
subscribes first and then reads the state therefore cannot miss an update. Pub/sub itself has no history.

The hash holds the same fields plus `session` and `updated_at`; the API's `app/services/job_state.py` reads it
and writes the first `queued` state. Keep the two in step.
"""

import json
import logging
import uuid
from datetime import datetime

import redis

from worker.config import settings

logger = logging.getLogger("worker.events")


def channel_for(session_id: uuid.UUID | str) -> str:
    return f"session:{session_id}:job"


def state_key(job_id: uuid.UUID | str) -> str:
    return f"job:{job_id}"


class JobEvents:
    def __init__(self, conn: redis.Redis, job_id: uuid.UUID | str, session_id: uuid.UUID | str):
        self._conn = conn
        self._job = str(job_id)
        self._session = str(session_id)
        self._channel = channel_for(session_id)

    def _emit(self, status: str, pct: int, *, url: str | None = None, error: str | None = None) -> None:
        message: dict = {"job": self._job, "status": status, "pct": pct}
        if url:
            message["url"] = url
        if error:
            message["error"] = error
        state = {
            **message,
            "session": self._session,
            "updated_at": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        }
        key = state_key(self._job)
        # A notification problem must never fail or mask the job itself; Postgres stays authoritative.
        try:
            pipe = self._conn.pipeline(transaction=True)
            pipe.delete(key)  # replace, so a stale field (an old `error`) cannot linger
            pipe.hset(key, mapping=state)
            pipe.expire(key, settings.job_state_ttl_seconds)
            pipe.publish(self._channel, json.dumps(message))
            pipe.execute()
        except redis.RedisError:
            logger.warning("event_publish_failed", extra={"job_id": self._job}, exc_info=True)

    def processing(self, pct: int) -> None:
        self._emit("processing", pct)

    def done(self, url: str) -> None:
        self._emit("done", 100, url=url)

    def failed(self, error: str, pct: int) -> None:
        self._emit("failed", pct, error=error)
