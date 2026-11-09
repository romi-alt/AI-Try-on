"""Health check for the worker container (Docker `HEALTHCHECK`): `python -m worker.healthcheck`.

Exit code 0 when this worker can do its job, 1 otherwise, with one line saying why. "Can do its job" means:
Postgres and Redis answer, and a worker for this process's queues has checked in with Redis in the last 90
seconds
(RQ workers heartbeat on their own, so a hung or dead process stops being listed).
"""

import sys
from datetime import UTC, datetime

import redis
from rq import Queue, Worker
from rq.serializers import JSONSerializer

from worker import db
from worker.config import settings
from worker.main import queue_names

MAX_HEARTBEAT_AGE_SECONDS = 90


def check(conn: redis.Redis | None = None, *, now: datetime | None = None) -> tuple[bool, str]:
    try:
        db.ping()
    except Exception as e:
        return False, f"postgres: {e.__class__.__name__}"
    try:
        conn = conn or redis.Redis.from_url(settings.redis_url, socket_connect_timeout=3)
        conn.ping()
    except Exception as e:
        return False, f"redis: {e.__class__.__name__}"

    now = now or datetime.now(UTC)
    for name in queue_names():
        queue = Queue(name, connection=conn, serializer=JSONSerializer)
        fresh = False
        for worker in Worker.all(queue=queue, connection=conn):
            beat = worker.last_heartbeat
            if beat is None:
                continue
            beat = beat if beat.tzinfo else beat.replace(tzinfo=UTC)
            if (now - beat).total_seconds() <= MAX_HEARTBEAT_AGE_SECONDS:
                fresh = True
                break
        if not fresh:
            return (
                False,
                f"no worker has checked in for queue {name!r} in the last {MAX_HEARTBEAT_AGE_SECONDS}s",
            )
    return True, "ok"


def main() -> int:
    ok, message = check()
    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
