"""The latest state of each try-on job, kept in a Redis hash `job:{id}`.

It lets a client that missed pub/sub messages (page reload, dropped socket, subscribed late) read
where the job is now. The worker keeps it current and publishes the same update in the same transaction;
the API writes the first `queued` state. Postgres stays the source of truth: `GET /jobs/{id}` falls back
to it when the hash is missing (expired, or Redis restarted).

Contract shared with services/worker/worker/events.py. Hash fields (all strings):

    job, session, status, pct, updated_at         always
    url                                           when status == "done"
    error                                         when status == "failed"

The published message is the subset {job, status, pct, url?, error?}: it never carries the session id.
"""

import json
import uuid
from datetime import datetime

import redis

from app.core.config import settings
from app.core.redis import get_redis


def job_channel(session_id: uuid.UUID | str) -> str:
    """Pub/sub channel carrying one session's job events."""
    return f"session:{session_id}:job"


def job_key(job_id: uuid.UUID | str) -> str:
    return f"job:{job_id}"


def write_state(
    conn: redis.Redis,
    job_id: uuid.UUID | str,
    session_id: uuid.UUID | str,
    status: str,
    pct: int,
    *,
    url: str | None = None,
    error: str | None = None,
) -> None:
    """Replace the job's state and publish it, atomically (one MULTI/EXEC).

    Doing both together means a subscriber is never told something the hash does not yet show, so a
    client that subscribes first and then reads the state can never miss an update.
    """
    message: dict = {"job": str(job_id), "status": status, "pct": pct}
    if url:
        message["url"] = url
    if error:
        message["error"] = error
    state = {
        **message,
        "session": str(session_id),
        "updated_at": datetime.now().astimezone().isoformat(timespec="milliseconds"),
    }
    pipe = conn.pipeline(transaction=True)
    pipe.delete(job_key(job_id))  # drop stale fields (e.g. an old `error`) rather than merging
    pipe.hset(job_key(job_id), mapping=state)
    pipe.expire(job_key(job_id), settings.job_state_ttl_seconds)
    pipe.publish(job_channel(session_id), json.dumps(message))
    pipe.execute()


def read_state(job_id: uuid.UUID | str) -> dict | None:
    """The stored hash, or None if there is none. Raises redis.RedisError if Redis is unreachable."""
    raw = get_redis().hgetall(job_key(job_id))
    return raw or None
