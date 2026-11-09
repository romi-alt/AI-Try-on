"""The worker's job pipeline with TRYON_PROVIDER=catvton, talking to the fake RunPod over a real socket."""

import io
import uuid

import pytest
from PIL import Image

from tests.helpers import add_capture, add_job, add_product, job_row
from worker import tasks
from worker.config import settings
from worker.fake_runpod import FakeRunPod, serve_in_thread

KEY = "integration-key"


@pytest.fixture
def runpod(monkeypatch):
    fake = FakeRunPod(api_key=KEY, cold_start=0.4, render_seconds=0.8, idle_timeout=30)
    server, base = serve_in_thread(fake)
    monkeypatch.setattr(settings, "tryon_provider", "catvton")
    monkeypatch.setattr(settings, "runpod_api_key", KEY)
    monkeypatch.setattr(settings, "runpod_endpoint_id", "ep-int")
    monkeypatch.setattr(settings, "runpod_base_url", base)
    monkeypatch.setattr(settings, "catvton_poll_interval_seconds", 0.1)
    yield fake
    server.shutdown()


@pytest.fixture
def job(pg, s3, redis_conn, listen):
    class Env:
        session_id = uuid.uuid4()
        product_id = add_product("Linen Shirt")
        capture_key = add_capture(session_id)
        job_id = add_job(session_id, [product_id], capture_key)
        events = listen(session_id)

    return Env


def test_a_job_runs_end_to_end_through_the_runpod_endpoint(job, runpod, s3):
    tasks.run_tryon_job(str(job.job_id))

    row = job_row(job.job_id)
    assert row.status == "done" and row.progress == 100 and row.result_url
    assert len(runpod.runs) == 1
    messages = job.events.messages()
    pcts = [m["pct"] for m in messages if m["status"] == "processing"]
    assert pcts == sorted(pcts) and len(set(pcts)) == len(pcts)
    assert len(pcts) > 4 and any(10 < p < 90 for p in pcts)  # the bar moved, it did not jump to done
    assert messages[-1]["status"] == "done"
    key = f"results/{job.session_id}/{job.job_id}.webp"
    stored = s3.get_object(Bucket=settings.s3_bucket, Key=key)["Body"].read()
    assert Image.open(io.BytesIO(stored)).format == "WEBP"


def test_a_handler_failure_reaches_the_shopper_as_a_readable_message(job, runpod):
    runpod.fail_code = "no_person"
    tasks.run_tryon_job(str(job.job_id))
    row = job_row(job.job_id)
    assert row.status == "failed"
    assert "fully in frame" in row.error


def test_a_wrong_key_is_reported_as_a_setup_problem_without_leaking_it(job, runpod, monkeypatch):
    monkeypatch.setattr(settings, "runpod_api_key", "wrong")
    tasks.run_tryon_job(str(job.job_id))
    row = job_row(job.job_id)
    assert row.status == "failed" and "isn't set up correctly" in row.error
    assert "wrong" not in row.error and KEY not in row.error
