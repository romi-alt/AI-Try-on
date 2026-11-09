"""JobEvents: the `job:{id}` hash and the pub/sub message are written together."""

import json
import threading
import uuid
from datetime import datetime

import pytest

from tests.helpers import add_capture, add_job, add_product
from worker import tasks
from worker.config import settings
from worker.events import JobEvents, state_key


@pytest.fixture
def job_ids():
    return uuid.uuid4(), uuid.uuid4()  # job, session


@pytest.fixture(autouse=True)
def clean_keys(redis_conn):
    before = set(redis_conn.scan_iter("job:*"))
    yield
    stale = set(redis_conn.scan_iter("job:*")) - before
    if stale:
        redis_conn.delete(*stale)


def state(conn, job_id) -> dict:
    return {k.decode(): v.decode() for k, v in conn.hgetall(state_key(job_id)).items()}


def test_processing_updates_the_hash_and_publishes(redis_conn, listen, job_ids):
    job, session = job_ids
    events = listen(session)

    JobEvents(redis_conn, job, session).processing(40)

    assert events.messages() == [{"job": str(job), "status": "processing", "pct": 40}]
    row = state(redis_conn, job)
    assert (row["job"], row["session"], row["status"], row["pct"]) == (
        str(job),
        str(session),
        "processing",
        "40",
    )
    assert "url" not in row and "error" not in row
    datetime.fromisoformat(row["updated_at"])  # a real timestamp, with a UTC offset
    assert datetime.fromisoformat(row["updated_at"]).tzinfo is not None


def test_the_hash_always_holds_the_latest_state(redis_conn, job_ids):
    job, session = job_ids
    ev = JobEvents(redis_conn, job, session)
    for pct in (0, 5, 30):
        ev.processing(pct)
    assert state(redis_conn, job)["pct"] == "30"

    ev.done("https://example.test/r.webp")

    row = state(redis_conn, job)
    assert (row["status"], row["pct"], row["url"]) == ("done", "100", "https://example.test/r.webp")


def test_failure_state_carries_the_error_and_no_url(redis_conn, listen, job_ids):
    job, session = job_ids
    events = listen(session)

    JobEvents(redis_conn, job, session).failed("Please try again.", 30)

    row = state(redis_conn, job)
    assert (row["status"], row["pct"], row["error"]) == ("failed", "30", "Please try again.")
    assert "url" not in row
    assert events.messages() == [
        {"job": str(job), "status": "failed", "pct": 30, "error": "Please try again."}
    ]


def test_a_new_state_replaces_the_old_one_instead_of_merging(redis_conn, job_ids):
    job, session = job_ids
    ev = JobEvents(redis_conn, job, session)
    ev.failed("old error", 10)
    ev.done("https://example.test/r.webp")  # e.g. a retried job

    row = state(redis_conn, job)
    assert row["status"] == "done" and "error" not in row


def test_the_state_expires(redis_conn, job_ids, monkeypatch):
    job, session = job_ids
    monkeypatch.setattr(settings, "job_state_ttl_seconds", 120)

    JobEvents(redis_conn, job, session).processing(5)

    assert 0 < redis_conn.ttl(state_key(job)) <= 120
    assert settings.job_state_ttl_seconds == 120
    from worker.config import Settings

    assert Settings(_env_file=None).job_state_ttl_seconds == 24 * 3600  # default: a day


def test_the_session_id_is_in_the_hash_but_never_in_messages(redis_conn, listen, job_ids):
    job, session = job_ids
    events = listen(session)
    JobEvents(redis_conn, job, session).done("https://example.test/r.webp")
    assert all("session" not in m for m in events.messages())
    assert state(redis_conn, job)["session"] == str(session)


def test_the_hash_is_never_behind_a_message_a_subscriber_has_received(pg, s3, redis_conn):
    """The property reconnecting clients rely on: subscribe, read the state, and nothing is missed."""
    session = uuid.uuid4()
    product = add_product("Linen Shirt")
    job = add_job(session, [product], add_capture(session))
    ps = redis_conn.pubsub()
    ps.psubscribe(f"session:{session}:*")
    assert ps.get_message(timeout=2)["type"] == "psubscribe"
    observed: list[tuple[int, int, str]] = []
    stop = threading.Event()

    def watch():
        while not stop.is_set():
            m = ps.get_message(timeout=0.1)
            if m and m["type"] == "pmessage":
                msg = json.loads(m["data"])
                row = redis_conn.hgetall(state_key(job))  # read the moment the message arrives
                observed.append((msg["pct"], int(row[b"pct"]), row[b"status"].decode()))

    thread = threading.Thread(target=watch)
    thread.start()
    try:
        tasks.run_tryon_job(str(job))
        threading.Event().wait(0.3)
    finally:
        stop.set()
        thread.join()
        ps.close()

    assert len(observed) >= 5
    assert all(hash_pct >= msg_pct for msg_pct, hash_pct, _ in observed), observed
    assert observed[-1][1:] == (100, "done")


def test_a_finished_job_leaves_its_final_state_in_the_hash(pg, s3, redis_conn):
    session = uuid.uuid4()
    job = add_job(session, [add_product("Tee")], add_capture(session))

    tasks.run_tryon_job(str(job))

    row = state(redis_conn, job)
    assert (row["status"], row["pct"]) == ("done", "100") and row["url"].startswith("http")
    assert row["session"] == str(session)
