"""Health checks for load balancers, Docker and uptime monitors.

- `GET /health` is *liveness*: the process is up and answering. It touches nothing else, so a database outage
  does not make an orchestrator restart a perfectly good API.
- `GET /health/ready` is *readiness*: can this instance do its job? Postgres and Redis are required; if
  either is
  down the answer is 503 and a proxy stops sending traffic. Storage and the try-on worker are reported but
  only
  mark the instance `degraded` (still 200): the shop can browse and sell without them, and a restart would
  not fix
  either. Nothing here exposes addresses or credentials, only ok / error and the error's class.
"""

import time
from datetime import UTC, datetime

from fastapi import APIRouter, Response
from rq import Worker
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.db import engine
from app.core.redis import get_redis, get_rq_redis
from app.core.storage import internal_client
from app.services.queue import get_queue

router = APIRouter(tags=["health"])

WORKER_HEARTBEAT_MAX_AGE_SECONDS = 90
CRITICAL = ("postgres", "redis")


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


def _postgres() -> str:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return "ok"


def _redis() -> str:
    get_redis().ping()
    return "ok"


def _storage() -> str:
    internal_client().head_bucket(Bucket=settings.s3_bucket)
    return "ok"


def _worker() -> str:
    """ok when a try-on worker has checked in recently."""
    now = datetime.now(UTC)
    for worker in Worker.all(queue=get_queue(), connection=get_rq_redis()):
        beat = worker.last_heartbeat
        if beat is not None:
            beat = beat if beat.tzinfo else beat.replace(tzinfo=UTC)
            if (now - beat).total_seconds() <= WORKER_HEARTBEAT_MAX_AGE_SECONDS:
                return "ok"
    return "error: no worker is listening on the try-on queue"


def _run(name: str, check) -> str:
    started = time.monotonic()
    try:
        result = check()
    except Exception as e:
        return f"error: {e.__class__.__name__}"
    return result if time.monotonic() - started < 5 else f"{result} (slow)"


@router.get("/health/ready")
async def ready(response: Response) -> dict:
    checks = {
        "postgres": await run_in_threadpool(_run, "postgres", _postgres),
        "redis": await run_in_threadpool(_run, "redis", _redis),
        "storage": await run_in_threadpool(_run, "storage", _storage),
        "worker": await run_in_threadpool(_run, "worker", _worker),
    }
    if any(not checks[name].startswith("ok") for name in CRITICAL):
        response.status_code = 503
        status = "down"
    elif any(not v.startswith("ok") for v in checks.values()):
        status = "degraded"
    else:
        status = "ok"
    return {"status": status, "checks": checks}
