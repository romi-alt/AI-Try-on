"""Progress events on Redis pub/sub.

Every update is a JSON object published to `session:{session_id}:job`:

    {"job": "<job id>", "status": "processing", "pct": 40}
    {"job": "<job id>", "status": "done",       "pct": 100, "url": "https://..."}
    {"job": "<job id>", "status": "failed",     "pct": 40,  "error": "readable message"}

Pub/sub has no history, so a client that subscribes late misses earlier messages. It should
subscribe first and then read `GET /tryon/{job}` once for the current state.
"""

import json
import logging
import uuid

import redis

logger = logging.getLogger("worker.events")


def channel_for(session_id: uuid.UUID | str) -> str:
    return f"session:{session_id}:job"


class JobEvents:
    def __init__(self, conn: redis.Redis, job_id: uuid.UUID | str, session_id: uuid.UUID | str):
        self._conn = conn
        self._job = str(job_id)
        self._channel = channel_for(session_id)

    def _publish(self, payload: dict) -> None:
        # A notification problem must never fail or mask the job itself; the DB stays authoritative.
        try:
            self._conn.publish(self._channel, json.dumps({"job": self._job, **payload}))
        except redis.RedisError:
            logger.warning("event_publish_failed", extra={"job_id": self._job}, exc_info=True)

    def processing(self, pct: int) -> None:
        self._publish({"status": "processing", "pct": pct})

    def done(self, url: str) -> None:
        self._publish({"status": "done", "pct": 100, "url": url})

    def failed(self, error: str, pct: int) -> None:
        self._publish({"status": "failed", "pct": pct, "error": error})
