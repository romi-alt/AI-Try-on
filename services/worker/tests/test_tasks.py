"""run_tryon_job end to end: real Postgres (private schema), real Redis pub/sub, real S3 server."""

import io
import logging
import uuid

import httpx
import pytest
from botocore.exceptions import ClientError
from PIL import Image
from rq.timeouts import JobTimeoutException

from tests.helpers import add_capture, add_job, add_product, job_row
from worker import tasks
from worker.config import settings
from worker.providers import FashnProvider, MockProvider, ProviderError, get_provider
from worker.providers.base import TryOnProvider, TryOnResult


@pytest.fixture
def env(pg, s3, redis_conn, listen):
    """A session with one queued job for one product, plus a listener on its channel."""

    class Env:
        session_id = uuid.uuid4()
        product_id = add_product("Linen Shirt")
        capture_key = add_capture(session_id)
        job_id = add_job(session_id, [product_id], capture_key)
        events = listen(session_id)

    return Env


class RecordingProvider(TryOnProvider):
    name = "recording"

    def __init__(self, steps=(50,), error: Exception | None = None):
        self.steps, self.error, self.request = steps, error, None

    def run(self, request, on_progress):
        self.request = request
        for pct in self.steps:
            on_progress(pct)
        if self.error:
            raise self.error
        buf = io.BytesIO()
        Image.new("RGB", (400, 600), (9, 99, 199)).save(buf, format="PNG")  # PNG: worker must convert
        return TryOnResult(image=buf.getvalue(), content_type="image/png")


def use(monkeypatch, provider):
    monkeypatch.setattr(tasks, "get_provider", lambda: provider)
    return provider


# --- success ---------------------------------------------------------------------------------


def test_success_stores_the_result_marks_done_and_publishes_the_url(env):
    tasks.run_tryon_job(str(env.job_id))

    row = job_row(env.job_id)
    assert (row.status, row.progress, row.error) == ("done", 100, None)
    messages = env.events.messages()
    last = messages[-1]
    assert last == {"job": str(env.job_id), "status": "done", "pct": 100, "url": row.result_url}


def test_result_url_serves_a_webp_stored_under_the_expected_key(env, s3):
    tasks.run_tryon_job(str(env.job_id))

    row = job_row(env.job_id)
    key = f"results/{env.session_id}/{env.job_id}.webp"
    stored = s3.get_object(Bucket=settings.s3_bucket, Key=key)
    assert stored["ContentType"] == "image/webp"
    assert key in row.result_url and "X-Amz-Signature" in row.result_url  # a signed, expiring link
    served = httpx.get(row.result_url)  # the URL given to the browser actually works
    assert served.status_code == 200
    assert Image.open(io.BytesIO(served.content)).format == "WEBP"
    assert served.content == stored["Body"].read()


def test_every_progress_step_is_published_in_order_and_persisted(env):
    tasks.run_tryon_job(str(env.job_id))

    messages = env.events.messages()
    steps = [m for m in messages if m["status"] == "processing"]
    pcts = [m["pct"] for m in steps]
    assert pcts == sorted(pcts) and len(set(pcts)) == len(pcts)  # strictly increasing, no repeats
    assert pcts[0] == 0 and 5 in pcts and 97 in pcts and max(pcts) < 100
    assert any(10 < p < 90 for p in pcts)  # the provider's own steps are in there
    assert all(m["job"] == str(env.job_id) for m in messages)
    assert [m["status"] for m in messages] == ["processing"] * len(steps) + ["done"]
    assert all(set(m) == {"job", "status", "pct"} for m in steps)


def test_progress_is_written_to_the_database_before_it_is_announced(env, monkeypatch):
    seen = []
    from worker import db

    real = db.set_progress

    def spy(job_id, pct):
        real(job_id, pct)
        seen.append((pct, job_row(job_id).progress))

    monkeypatch.setattr(db, "set_progress", spy)
    tasks.run_tryon_job(str(env.job_id))

    assert seen and all(pct == stored for pct, stored in seen)


def test_provider_progress_is_scaled_into_the_middle_of_the_bar(env, monkeypatch):
    use(monkeypatch, RecordingProvider(steps=(0, 25, 50, 75, 100)))

    tasks.run_tryon_job(str(env.job_id))

    pcts = [m["pct"] for m in env.events.messages() if m["status"] == "processing"]
    assert pcts == [0, 5, 10, 30, 50, 70, 90, 92, 97]


def test_an_outfit_reaches_the_provider_in_the_shoppers_order(env, monkeypatch):
    second = add_product("Trousers", "bottom")
    third = add_product("Scarf", "accessory")
    job_id = add_job(env.session_id, [second, env.product_id, third], env.capture_key)
    provider = use(monkeypatch, RecordingProvider())

    tasks.run_tryon_job(str(job_id))

    assert [g.name for g in provider.request.garments] == ["Trousers", "Linen Shirt", "Scarf"]
    assert [g.category for g in provider.request.garments] == ["bottom", "top", "accessory"]
    assert Image.open(io.BytesIO(provider.request.garments[0].image)).format == "PNG"
    assert Image.open(io.BytesIO(provider.request.person_image)).format == "WEBP"


def test_garment_images_hosted_elsewhere_are_downloaded_over_http(env, monkeypatch):
    from tests.helpers import garment_png

    monkeypatch.setattr(
        httpx,
        "get",
        lambda url, **kw: httpx.Response(200, content=garment_png(), request=httpx.Request("GET", url)),
    )
    pid = add_product("Remote Dress", "dress", external_url="https://images.example.com/dress.png")
    job_id = add_job(env.session_id, [pid], env.capture_key)
    provider = use(monkeypatch, RecordingProvider())

    tasks.run_tryon_job(str(job_id))

    assert job_row(job_id).status == "done" and provider.request.garments[0].name == "Remote Dress"


def test_provider_result_in_another_format_is_converted_to_webp(env, monkeypatch, s3):
    use(monkeypatch, RecordingProvider())
    tasks.run_tryon_job(str(env.job_id))
    body = s3.get_object(Bucket=settings.s3_bucket, Key=f"results/{env.session_id}/{env.job_id}.webp")[
        "Body"
    ].read()
    assert Image.open(io.BytesIO(body)).format == "WEBP"


# --- failure ---------------------------------------------------------------------------------


def assert_failed(env, message_part: str):
    row = job_row(env.job_id)
    assert row.status == "failed" and row.result_url is None
    assert message_part in row.error
    last = env.events.messages()[-1]
    assert last["status"] == "failed" and last["error"] == row.error and isinstance(last["pct"], int)
    assert last["job"] == str(env.job_id) and "url" not in last
    return row, last


def test_a_provider_error_fails_the_job_with_its_readable_message(env, monkeypatch):
    use(
        monkeypatch,
        RecordingProvider(
            steps=(40,), error=ProviderError("We couldn't see your full body.", detail="PoseError")
        ),
    )

    tasks.run_tryon_job(str(env.job_id))

    _, last = assert_failed(env, "full body")
    assert last["pct"] == 10 + int(0.4 * 80)  # reports how far it got
    assert "PoseError" not in last["error"]


def test_mock_fail_flag_exercises_the_failure_path(env, monkeypatch):
    monkeypatch.setattr(settings, "mock_fail", True)
    tasks.run_tryon_job(str(env.job_id))
    assert_failed(env, "MOCK_FAIL")


def test_an_unexpected_exception_is_logged_but_never_leaked(env, monkeypatch, caplog):
    use(monkeypatch, RecordingProvider(error=ValueError("secret internals: /srv/app/model.py line 42")))

    with caplog.at_level(logging.ERROR, logger="worker.tasks"):
        tasks.run_tryon_job(str(env.job_id))

    row, _ = assert_failed(env, "Something went wrong")
    assert "secret" not in row.error and "ValueError" not in row.error
    assert any(
        "secret internals" in (r.exc_text or "") or r.exc_info for r in caplog.records
    )  # full detail is in the logs


def test_a_deleted_capture_gives_a_helpful_message(env, s3):
    s3.delete_object(Bucket=settings.s3_bucket, Key=env.capture_key)  # what the 1-hour cleanup does
    tasks.run_tryon_job(str(env.job_id))
    assert_failed(env, "take a new one")


def test_a_deleted_product_is_a_readable_failure(env, pg):
    from sqlalchemy import delete

    from worker import db

    with db.engine.begin() as conn:
        conn.execute(delete(db.products).where(db.products.c.id == env.product_id))
    tasks.run_tryon_job(str(env.job_id))
    assert_failed(env, "no longer available")


def test_a_missing_garment_image_names_the_product(env, s3):
    s3.delete_object(Bucket=settings.s3_bucket, Key=f"products/{env.product_id}.png")
    tasks.run_tryon_job(str(env.job_id))
    assert_failed(env, "'Linen Shirt'")


def test_storage_outage_while_reading_the_capture_is_readable(env, monkeypatch):
    def down(key):
        raise ClientError({"Error": {"Code": "500", "Message": "boom"}}, "GetObject")

    monkeypatch.setattr("worker.storage.get_bytes", down)
    tasks.run_tryon_job(str(env.job_id))
    assert_failed(env, "photo storage")


def test_storage_outage_while_saving_the_result_is_readable(env, monkeypatch):
    def down(key, data, content_type):
        raise ClientError({"Error": {"Code": "500", "Message": "boom"}}, "PutObject")

    use(monkeypatch, RecordingProvider())
    monkeypatch.setattr("worker.storage.put_bytes", down)
    tasks.run_tryon_job(str(env.job_id))
    assert_failed(env, "photo storage")


def test_an_rq_timeout_inside_the_job_is_reported_as_too_slow(env, monkeypatch):
    use(monkeypatch, RecordingProvider(error=JobTimeoutException("Task exceeded maximum timeout value")))
    tasks.run_tryon_job(str(env.job_id))
    assert_failed(env, "took too long")


def test_an_unreadable_provider_result_fails_cleanly(env, monkeypatch):
    class Garbage(RecordingProvider):
        def run(self, request, on_progress):
            return TryOnResult(image=b"not an image", content_type="image/png")

    use(monkeypatch, Garbage())
    tasks.run_tryon_job(str(env.job_id))
    assert_failed(env, "could not be processed")


# --- idempotency and edge cases ----------------------------------------------------------------


def test_a_missing_job_is_ignored(pg, redis_conn):
    tasks.run_tryon_job(str(uuid.uuid4()))  # must not raise


def test_a_job_already_claimed_is_not_run_twice(env, monkeypatch):
    provider = use(monkeypatch, RecordingProvider())
    tasks.run_tryon_job(str(env.job_id))
    first = env.events.messages()

    tasks.run_tryon_job(str(env.job_id))  # redelivered

    assert provider.request is not None and env.events.messages() == []
    assert first[-1]["status"] == "done" and job_row(env.job_id).status == "done"


def test_a_job_that_is_processing_elsewhere_is_left_alone(env, monkeypatch):
    other = add_job(env.session_id, [env.product_id], env.capture_key, status="processing")
    provider = use(monkeypatch, RecordingProvider())

    tasks.run_tryon_job(str(other))

    assert provider.request is None and job_row(other).status == "processing"


def test_events_only_go_to_the_owning_sessions_channel(env, listen):
    stranger = listen(uuid.uuid4())
    tasks.run_tryon_job(str(env.job_id))
    assert env.events.messages() and stranger.messages() == []


def test_a_redis_failure_while_reporting_does_not_fail_the_job(env, monkeypatch):
    import redis
    import redis.client

    def down(self, *args, **kwargs):
        raise redis.ConnectionError("down")

    monkeypatch.setattr(redis.client.Pipeline, "execute", down)  # events go out through a pipeline

    tasks.run_tryon_job(str(env.job_id))

    assert job_row(env.job_id).status == "done" and env.events.messages() == []


# --- RQ failure callback -------------------------------------------------------------------------


class FakeRqJob:
    def __init__(self, job_id):
        self.args = (str(job_id),)


def test_failure_callback_fails_a_job_stuck_in_processing(env, redis_conn):
    from worker import db

    db.claim_job(env.job_id)  # the worker died after claiming it
    db.set_progress(env.job_id, 30)

    tasks.handle_rq_failure(FakeRqJob(env.job_id), redis_conn, RuntimeError, RuntimeError("killed"), None)

    row = job_row(env.job_id)
    assert row.status == "failed" and "try again" in row.error
    last = env.events.messages()[-1]
    assert last["status"] == "failed" and last["error"] == row.error
    assert last["pct"] == 30  # reports how far it had got, not zero


def test_failure_callback_reports_timeouts_distinctly(env, redis_conn):
    tasks.handle_rq_failure(
        FakeRqJob(env.job_id), redis_conn, JobTimeoutException, JobTimeoutException("t"), None
    )
    assert "took too long" in job_row(env.job_id).error


def test_failure_callback_never_overwrites_a_finished_job(env, redis_conn):
    tasks.run_tryon_job(str(env.job_id))
    env.events.messages()

    tasks.handle_rq_failure(FakeRqJob(env.job_id), redis_conn, RuntimeError, RuntimeError("late"), None)

    assert job_row(env.job_id).status == "done" and env.events.messages() == []


def test_failure_callback_ignores_unknown_jobs(pg, redis_conn):
    tasks.handle_rq_failure(FakeRqJob(uuid.uuid4()), redis_conn, RuntimeError, RuntimeError("x"), None)


# --- stale job reaper ----------------------------------------------------------------------------


def backdate(job_id, seconds):
    from sqlalchemy import text

    from worker import db

    with db.engine.begin() as conn:
        conn.execute(
            text("UPDATE tryon_jobs SET updated_at = now() - make_interval(secs => :s) WHERE id = :id"),
            {"s": seconds, "id": job_id},
        )


def test_reaper_fails_jobs_whose_whole_worker_died(env, redis_conn):
    from worker import db

    db.claim_job(env.job_id)
    db.set_progress(env.job_id, 40)
    backdate(env.job_id, settings.job_timeout_seconds + 120)

    assert tasks.reap_stale_jobs(redis_conn) == 1

    row = job_row(env.job_id)
    assert row.status == "failed" and "try again" in row.error
    last = env.events.messages()[-1]
    assert last == {"job": str(env.job_id), "status": "failed", "pct": 40, "error": row.error}


def test_reaper_leaves_live_finished_and_queued_jobs_alone(env, redis_conn):

    live = add_job(env.session_id, [env.product_id], env.capture_key, status="processing")
    backdate(live, 30)  # recently updated: still running
    done = add_job(env.session_id, [env.product_id], env.capture_key, status="done")
    backdate(done, 99999)
    backdate(env.job_id, 99999)  # still queued, however old: not the reaper's concern

    assert tasks.reap_stale_jobs(redis_conn) == 0

    assert [job_row(j).status for j in (live, done, env.job_id)] == ["processing", "done", "queued"]
    assert env.events.messages() == []


def test_reaper_does_nothing_when_there_is_nothing_to_reap(pg, redis_conn):
    assert tasks.reap_stale_jobs(redis_conn) == 0


# --- provider selection ----------------------------------------------------------------------------


def test_provider_is_chosen_by_the_environment(monkeypatch):
    monkeypatch.setattr(settings, "tryon_provider", "mock")
    assert isinstance(get_provider(), MockProvider)

    monkeypatch.setattr(settings, "tryon_provider", "fashn")
    monkeypatch.setattr(settings, "fashn_api_key", "k")
    assert isinstance(get_provider(), FashnProvider)


def test_fashn_without_a_key_fails_fast(monkeypatch):
    monkeypatch.setattr(settings, "tryon_provider", "fashn")
    monkeypatch.setattr(settings, "fashn_api_key", None)
    with pytest.raises(RuntimeError, match="FASHN_API_KEY"):
        get_provider()


def test_unknown_provider_name_is_rejected_by_settings():
    from pydantic import ValidationError

    from worker.config import Settings

    with pytest.raises(ValidationError):
        Settings(_env_file=None, tryon_provider="banana")
    assert Settings(_env_file=None, tryon_provider="fashn").tryon_provider == "fashn"
