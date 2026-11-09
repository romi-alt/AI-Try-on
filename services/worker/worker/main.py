"""Start the RQ worker for the try-on queue.

python -m worker.main
"""

import logging

import redis
from rq import Queue, Worker
from rq.serializers import JSONSerializer

from worker import db, tasks
from worker.config import settings
from worker.logging_setup import configure_logging
from worker.providers import get_provider

logger = logging.getLogger("worker")


class TryOnWorker(Worker):
    def run_maintenance_tasks(self):
        super().run_maintenance_tasks()
        if settings.tryon_queue_name not in [q.name for q in self.queues]:
            return  # the reaper only concerns try-on jobs
        try:
            tasks.reap_stale_jobs(self.connection)
        except Exception:
            logger.exception("reaper_failed")


def queue_names() -> list[str]:
    """The queues this process works, from WORKER_QUEUES (`tryon` or `assets`; a list means priority
    order)."""
    mapping = {"tryon": settings.tryon_queue_name, "assets": settings.assets_queue_name}
    wanted = [q.strip() for q in settings.worker_queues.split(",") if q.strip()]
    unknown = [q for q in wanted if q not in mapping]
    if unknown or not wanted:
        raise SystemExit(f"WORKER_QUEUES must list tryon and/or assets, got {settings.worker_queues!r}")
    return [mapping[q] for q in wanted]


def build_worker(queues: Queue | list[Queue], conn: redis.Redis) -> Worker:
    return TryOnWorker(
        queues if isinstance(queues, list) else [queues],
        connection=conn,
        serializer=JSONSerializer,
        work_horse_killed_handler=tasks.handle_work_horse_killed,
    )


def main() -> None:
    configure_logging(settings.log_level)
    names = queue_names()
    serves_tryon = settings.tryon_queue_name in names

    provider = get_provider() if serves_tryon else None  # fail fast on a bad TRYON_PROVIDER or a missing key
    db.ping()

    conn = redis.Redis.from_url(settings.redis_url)
    conn.ping()
    if serves_tryon:
        try:
            tasks.reap_stale_jobs(conn)  # clean up after a previous crash before taking new work
        except Exception:
            # e.g. `make migrate` has not run yet. Jobs can't be claimed without the tables either.
            logger.warning("startup_reap_skipped", exc_info=True)

    queues = [Queue(n, connection=conn, serializer=JSONSerializer) for n in names]
    logger.info(
        "worker_started",
        extra={"provider": provider.name if provider else None, "queues": [q.name for q in queues]},
    )
    build_worker(queues, conn).work(with_scheduler=False)


if __name__ == "__main__":
    main()
