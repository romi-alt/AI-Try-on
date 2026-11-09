"""GET /jobs/{id}: the polling fallback and the first call after a reconnect."""

import json
import uuid
from datetime import datetime

import redis

from app.core.config import settings
from app.core.redis import get_redis
from app.models import JobStatus, TryOnJob
from app.services.job_state import job_channel, job_key, write_state
from tests.helpers import make_product, make_session, put_capture_for


async def queued_job(api, adb) -> tuple[str, str]:
    """Create a job the way the kiosk does (POST /tryon). Returns (session id, job id)."""
    sid = await make_session(api)
    product = await make_product(adb)
    key = await put_capture_for(sid)
    r = await api.post(
        "/tryon", json={"session_id": sid, "capture_key": key, "product_ids": [str(product.id)]}
    )
    assert r.status_code == 202, r.text
    return sid, r.json()["job_id"]


# --- right after POST /tryon --------------------------------------------------------------------


async def test_a_job_is_pollable_the_moment_it_is_queued(api, adb, s3, rq_queue):
    sid, job = await queued_job(api, adb)  # no worker has touched it yet

    r = await api.get(f"/jobs/{job}")

    assert r.status_code == 200
    body = r.json()
    assert (body["job"], body["status"], body["pct"]) == (job, "queued", 0)
    assert body["url"] is None and body["error"] is None
    assert datetime.fromisoformat(body["updated_at"]).tzinfo is not None
    assert r.headers["cache-control"] == "no-store"  # polling must never be served from a cache


async def test_the_session_id_is_never_exposed(api, adb, s3, rq_queue):
    sid, job = await queued_job(api, adb)
    body = (await api.get(f"/jobs/{job}")).json()
    assert "session" not in body and sid not in json.dumps(body)  # it is the key to the session's events


async def test_queueing_writes_the_state_hash_with_a_ttl(api, adb, s3, rq_queue):
    sid, job = await queued_job(api, adb)

    raw = get_redis().hgetall(job_key(job))

    assert (raw["job"], raw["session"], raw["status"], raw["pct"]) == (job, sid, "queued", "0")
    assert 0 < get_redis().ttl(job_key(job)) <= settings.job_state_ttl_seconds


async def test_queueing_announces_the_job_on_the_session_channel(api, adb, s3, rq_queue):
    sid = await make_session(api)
    product = await make_product(adb)
    key = await put_capture_for(sid)
    pubsub = get_redis().pubsub()
    pubsub.subscribe(job_channel(sid))
    assert pubsub.get_message(timeout=2)["type"] == "subscribe"

    r = await api.post(
        "/tryon", json={"session_id": sid, "capture_key": key, "product_ids": [str(product.id)]}
    )

    message = pubsub.get_message(timeout=2)
    pubsub.close()
    assert json.loads(message["data"]) == {"job": r.json()["job_id"], "status": "queued", "pct": 0}


async def test_the_hash_is_written_before_the_job_reaches_the_queue(api, adb, s3, rq_queue, monkeypatch):
    """So a worker that starts immediately can never be overwritten by a late `queued`."""
    sid = await make_session(api)
    product = await make_product(adb)
    key = await put_capture_for(sid)
    seen = {}
    real_enqueue = rq_queue.enqueue

    def spy(*args, **kwargs):
        seen["hash_at_enqueue"] = get_redis().hget(job_key(kwargs["job_id"]), "status")
        return real_enqueue(*args, **kwargs)

    monkeypatch.setattr("app.services.queue.get_queue", lambda: type("Q", (), {"enqueue": staticmethod(spy)}))
    await api.post("/tryon", json={"session_id": sid, "capture_key": key, "product_ids": [str(product.id)]})

    assert seen["hash_at_enqueue"] == "queued"


# --- following the worker ------------------------------------------------------------------------


async def test_it_reports_each_state_the_worker_writes(api, adb, s3, rq_queue):
    sid, job = await queued_job(api, adb)
    r = get_redis()

    write_state(r, job, sid, "processing", 40)
    processing = (await api.get(f"/jobs/{job}")).json()
    write_state(r, job, sid, "done", 100, url="https://example.test/result.webp")
    done = (await api.get(f"/jobs/{job}")).json()

    assert (processing["status"], processing["pct"], processing["url"]) == ("processing", 40, None)
    assert (done["status"], done["pct"], done["url"]) == ("done", 100, "https://example.test/result.webp")
    assert done["error"] is None


async def test_a_failed_job_reports_its_error_and_no_url(api, adb, s3, rq_queue):
    sid, job = await queued_job(api, adb)
    write_state(get_redis(), job, sid, "failed", 30, error="Your photo is no longer available.")

    body = (await api.get(f"/jobs/{job}")).json()

    assert (body["status"], body["pct"], body["error"], body["url"]) == (
        "failed",
        30,
        "Your photo is no longer available.",
        None,
    )


async def test_the_redis_hash_is_what_is_served_when_both_exist(api, adb, s3, rq_queue):
    sid, job = await queued_job(api, adb)  # the database row says queued / 0
    write_state(get_redis(), job, sid, "processing", 65)

    assert (await api.get(f"/jobs/{job}")).json()["pct"] == 65


# --- falling back to Postgres --------------------------------------------------------------------


async def set_row(adb, job_id: str, **fields) -> None:
    row = await adb.get(TryOnJob, uuid.UUID(job_id))
    for k, v in fields.items():
        setattr(row, k, v)
    await adb.flush()
    await adb.refresh(row)


async def test_it_falls_back_to_the_database_when_the_hash_is_gone(api, adb, s3, rq_queue):
    sid, job = await queued_job(api, adb)
    await set_row(adb, job, status=JobStatus.done, progress=100, result_url="https://example.test/db.webp")
    get_redis().delete(job_key(job))  # expired, or Redis restarted

    body = (await api.get(f"/jobs/{job}")).json()

    assert (body["status"], body["pct"], body["url"], body["error"]) == (
        "done",
        100,
        "https://example.test/db.webp",
        None,
    )


async def test_it_falls_back_to_the_database_when_redis_is_down(api, adb, s3, rq_queue, monkeypatch):
    sid, job = await queued_job(api, adb)
    await set_row(adb, job, status=JobStatus.failed, progress=40, error="Please try again.")

    def down(job_id):
        raise redis.ConnectionError("redis is down")

    monkeypatch.setattr("app.api.jobs.read_state", down)

    r = await api.get(f"/jobs/{job}")

    assert r.status_code == 200
    assert (r.json()["status"], r.json()["pct"], r.json()["error"]) == ("failed", 40, "Please try again.")


async def test_a_corrupt_hash_is_ignored_in_favour_of_the_database(api, adb, s3, rq_queue):
    sid, job = await queued_job(api, adb)
    await set_row(adb, job, status=JobStatus.processing, progress=55)
    get_redis().delete(job_key(job))
    get_redis().hset(job_key(job), mapping={"status": "processing"})  # no pct / updated_at

    body = (await api.get(f"/jobs/{job}")).json()

    assert (body["status"], body["pct"]) == ("processing", 55)


async def test_unknown_and_malformed_ids(api, rq_queue):
    assert (await api.get(f"/jobs/{uuid.uuid4()}")).status_code == 404
    assert (await api.get("/jobs/not-a-uuid")).status_code == 422


async def test_a_job_that_failed_to_enqueue_is_announced_as_failed(api, adb, s3, rq_queue, monkeypatch):
    sid = await make_session(api)
    product = await make_product(adb)
    key = await put_capture_for(sid)

    def down(job_id, session_id):
        raise ConnectionError("queue unavailable")

    monkeypatch.setattr("app.api.tryon.enqueue_tryon", down)
    r = await api.post(
        "/tryon", json={"session_id": sid, "capture_key": key, "product_ids": [str(product.id)]}
    )
    assert r.status_code == 503

    raw = get_redis().hgetall(
        next(k for k in get_redis().scan_iter("job:*") if get_redis().hget(k, "session") == sid)
    )
    assert raw["status"] == "failed" and "try again" in raw["error"].lower()
