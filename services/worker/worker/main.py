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
        try:
            tasks.reap_stale_jobs(self.connection)
        except Exception:
            logger.exception("reaper_failed")


def build_worker(queue: Queue, conn: redis.Redis) -> Worker:
    return TryOnWorker(
        [queue],
        connection=conn,
        serializer=JSONSerializer,
        work_horse_killed_handler=tasks.handle_work_horse_killed,
    )


def main() -> None:
    configure_logging(settings.log_level)

    provider = get_provider()  # fail fast on a bad TRYON_PROVIDER or a missing FASHN_API_KEY
    db.ping()

    conn = redis.Redis.from_url(settings.redis_url)
    conn.ping()
    try:
        tasks.reap_stale_jobs(conn)  # clean up after a previous crash before taking new work
    except Exception:
        # e.g. `make migrate` has not run yet. Jobs can't be claimed without the tables either.
        logger.warning("startup_reap_skipped", exc_info=True)

    queue = Queue(settings.tryon_queue_name, connection=conn, serializer=JSONSerializer)
    logger.info("worker_started", extra={"provider": provider.name, "queue": queue.name})
    build_worker(queue, conn).work(with_scheduler=False)


if __name__ == "__main__":
    main()
