"""The real RQ machinery: enqueue exactly as the API does, then run real workers."""

import uuid

import pytest
import redis
from rq import Callback, Queue, SimpleWorker
from rq.serializers import JSONSerializer

from tests.helpers import add_capture, add_job, add_product, job_row
from worker.config import settings
from worker.main import build_worker


@pytest.fixture
def queue(redis_conn):
    q = Queue(
        f"test-{uuid.uuid4().hex[:10]}",
        connection=redis.Redis.from_url(settings.redis_url),
        serializer=JSONSerializer,
    )
    yield q
    q.empty()


@pytest.fixture
def env(pg, s3, redis_conn, listen):
    class Env:
        session_id = uuid.uuid4()
        product_id = add_product("Linen Shirt")
        capture_key = add_capture(session_id)
        job_id = add_job(session_id, [product_id], capture_key)
        events = listen(session_id)

    return Env


def enqueue_like_the_api(queue: Queue, job_id, **overrides):
    """Mirrors app/services/queue.py::enqueue_tryon."""
    opts = {
        "job_id": str(job_id),
        "job_timeout": 300,
        "result_ttl": 0,
        "failure_ttl": 3600,
        "on_failure": Callback("worker.tasks.handle_rq_failure"),
    }
    return queue.enqueue(
        overrides.pop("func", "worker.tasks.run_tryon_job"), str(job_id), **{**opts, **overrides}
    )


def test_in_process_worker_runs_a_job_enqueued_the_way_the_api_does(env, queue):
    enqueue_like_the_api(queue, env.job_id)

    SimpleWorker([queue], connection=queue.connection, serializer=JSONSerializer).work(burst=True)

    assert job_row(env.job_id).status == "done"
    assert env.events.messages()[-1]["status"] == "done"
    assert len(queue) == 0


def test_forked_worker_processes_a_job_end_to_end(env, queue):
    enqueue_like_the_api(queue, env.job_id)

    build_worker(queue, queue.connection).work(burst=True)

    row = job_row(env.job_id)
    assert row.status == "done" and row.progress == 100 and row.result_url
    messages = env.events.messages()
    assert messages[0]["status"] == "processing" and messages[-1] == {
        "job": str(env.job_id),
        "status": "done",
        "pct": 100,
        "url": row.result_url,
    }


def test_forked_jobs_do_not_share_the_parents_database_connection(env, queue):
    """Regression: the parent (which uses the DB for the reaper and kill handler) forks one child
    per job. Children that inherited its pooled connection failed with 'prepared statement already
    exists' on every job after the first."""
    from worker import db

    db.fetch_job(env.job_id)  # the parent now holds a pooled, prepared-statement-bearing connection
    second = add_job(env.session_id, [env.product_id], env.capture_key)
    enqueue_like_the_api(queue, env.job_id)
    enqueue_like_the_api(queue, second)

    build_worker(queue, queue.connection).work(burst=True)

    rows = [job_row(env.job_id), job_row(second)]
    assert [r.status for r in rows] == ["done", "done"], [r.error for r in rows]


def test_a_real_rq_timeout_is_reported_as_too_slow(env, queue, monkeypatch):
    monkeypatch.setattr(settings, "mock_duration_seconds", 20.0)
    monkeypatch.setattr(settings, "mock_steps", 1)
    enqueue_like_the_api(queue, env.job_id, job_timeout=1)

    build_worker(queue, queue.connection).work(burst=True)

    row = job_row(env.job_id)
    assert row.status == "failed" and "took too long" in row.error
    assert env.events.messages()[-1]["status"] == "failed"


def test_a_killed_worker_does_not_leave_the_job_processing_forever(env, queue):
    from worker import db

    db.claim_job(env.job_id)  # as run_tryon_job does just before the process is killed
    enqueue_like_the_api(queue, env.job_id, func="tests.crash_jobs.die")

    build_worker(queue, queue.connection).work(burst=True)

    row = job_row(env.job_id)
    assert row.status == "failed" and "try again" in row.error
    assert env.events.messages()[-1]["status"] == "failed"


def test_the_queue_name_comes_from_settings(monkeypatch):
    from worker.config import Settings

    assert Settings(_env_file=None).tryon_queue_name == "tryon"
    monkeypatch.setenv("TRYON_QUEUE_NAME", "custom")
    assert Settings(_env_file=None).tryon_queue_name == "custom"
