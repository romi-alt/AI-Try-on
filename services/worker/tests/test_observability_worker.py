"""Worker: Sentry never carries a photo; the container health check; the tryon_done event."""

import base64
import io
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import redis
import sentry_sdk
from PIL import Image
from rq import Queue, Worker
from rq.serializers import JSONSerializer
from sentry_sdk.transport import Transport

from tests.helpers import add_capture, add_job, add_product, job_row
from worker import analytics, healthcheck, observability, tasks
from worker.config import settings


def photo_b64() -> str:
    out = io.BytesIO()
    Image.new("RGB", (240, 320), (200, 120, 90)).save(out, format="JPEG")
    return base64.b64encode(out.getvalue()).decode()


# --- Sentry --------------------------------------------------------------------------------------


class Capture(Transport):
    def __init__(self, options=None):
        super().__init__(options)
        self.events = []

    def capture_envelope(self, envelope):
        for item in envelope.items:
            if item.headers.get("type") == "event":
                self.events.append(item.payload.json)


def test_an_error_in_a_job_is_reported_without_the_photo_or_locals(monkeypatch):
    monkeypatch.setattr(settings, "sentry_dsn", "http://public@localhost:9/1")
    transport = Capture()
    assert observability.init_sentry(service="worker-tryon", transport=transport) is True
    photo = photo_b64()

    def render(person_image):
        raise RuntimeError(f"provider said: {person_image[:400]}")

    try:
        render(photo)
    except RuntimeError:
        sentry_sdk.capture_exception()
    sentry_sdk.flush()
    sentry_sdk.get_client().close()
    sentry_sdk.init()
    (event,) = transport.events
    text = json.dumps(event)
    assert photo[:100] not in text and "/9j/" not in text
    assert all("vars" not in f for f in event["exception"]["values"][0]["stacktrace"]["frames"])
    assert event["tags"]["service"] == "worker-tryon"


def test_sentry_is_off_without_a_dsn(monkeypatch):
    monkeypatch.setattr(settings, "sentry_dsn", "")
    assert observability.init_sentry() is False


def test_the_scrubber_drops_request_data_and_users():
    out = observability.scrub_event(
        {
            "user": {"id": "x"},
            "request": {"data": "d", "headers": {"X-Admin-Key": "k"}, "url": "https://x/m/K7TQ4M2X"},
        }
    )
    assert "user" not in out and out["request"] == {"url": "https://x/m/[code]"}


# --- health check --------------------------------------------------------------------------------


@pytest.fixture
def conn(redis_conn):
    return redis_conn


def make_worker(conn, queue="hc-test-queue"):
    q = Queue(queue, connection=conn, serializer=JSONSerializer)
    w = Worker([q], connection=conn, serializer=JSONSerializer, name=f"hc-{uuid.uuid4().hex[:8]}")
    w.register_birth()
    return w


def test_healthy_when_postgres_redis_and_a_fresh_worker_are_present(pg, conn, monkeypatch):
    monkeypatch.setattr(healthcheck, "queue_names", lambda: ["hc-test-queue"])
    w = make_worker(conn)
    try:
        assert healthcheck.check(conn) == (True, "ok")
    finally:
        w.register_death()


def test_unhealthy_when_no_worker_has_checked_in(pg, conn, monkeypatch):
    monkeypatch.setattr(healthcheck, "queue_names", lambda: ["hc-nobody-here"])
    ok, message = healthcheck.check(conn)
    assert ok is False and "hc-nobody-here" in message


def test_unhealthy_when_the_only_worker_has_gone_quiet(pg, conn, monkeypatch):
    monkeypatch.setattr(healthcheck, "queue_names", lambda: ["hc-test-queue"])
    w = make_worker(conn)
    try:
        later = datetime.now(UTC) + timedelta(seconds=healthcheck.MAX_HEARTBEAT_AGE_SECONDS + 30)
        assert healthcheck.check(conn, now=later)[0] is False
    finally:
        w.register_death()


def test_unhealthy_when_postgres_is_down(conn, monkeypatch):
    def down():
        raise ConnectionError("db.internal refused")

    monkeypatch.setattr(healthcheck.db, "ping", down)
    ok, message = healthcheck.check(conn)
    assert ok is False and message == "postgres: ConnectionError"  # no hostnames or messages leak


def test_unhealthy_when_redis_is_down(pg, monkeypatch):
    class Dead:
        def ping(self):
            raise redis.ConnectionError("nope")

    ok, message = healthcheck.check(Dead())
    assert ok is False and message.startswith("redis:")


def test_main_exits_nonzero_when_unhealthy(monkeypatch, capsys):
    monkeypatch.setattr(healthcheck, "check", lambda: (False, "redis: ConnectionError"))
    assert healthcheck.main() == 1
    assert capsys.readouterr().out.strip() == "redis: ConnectionError"


# --- the tryon_done event ------------------------------------------------------------------------


class Recorder:
    def __init__(self):
        self.sent = []

    def capture(self, event, session_id, **props):
        self.sent.append((event, str(session_id), props))


def test_a_finished_job_sends_one_anonymous_tryon_done_event(pg, s3, redis_conn, monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(analytics, "_tracker", rec)
    session_id = uuid.uuid4()
    a, b = add_product("Top", "top"), add_product("Trousers", "bottom")
    job_id = add_job(session_id, [a, b], add_capture(session_id))

    tasks.run_tryon_job(str(job_id))

    assert job_row(job_id).status == "done"
    ((event, who, props),) = rec.sent
    assert event == "tryon_done" and who == str(session_id)
    assert set(props) == {"product_count", "recommended_count", "render_seconds", "total_seconds", "provider"}
    assert (props["product_count"], props["recommended_count"], props["provider"]) == (2, 0, "mock")
    assert props["total_seconds"] >= props["render_seconds"] >= 0
    assert "result_url" not in json.dumps(props) and "capture" not in json.dumps(props)


def test_a_failed_job_sends_no_event(pg, s3, redis_conn, monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(analytics, "_tracker", rec)
    session_id = uuid.uuid4()
    job_id = add_job(
        session_id, [add_product("Top", "top")], f"captures/{session_id}/gone.webp"
    )  # no such photo

    tasks.run_tryon_job(str(job_id))

    assert job_row(job_id).status == "failed"
    assert rec.sent == []


def test_the_worker_and_api_copies_of_the_shared_modules_are_identical():
    from pathlib import Path

    here = Path(__file__).resolve().parents[1] / "worker"
    api = Path(__file__).resolve().parents[2] / "api" / "app"
    assert (here / "analytics.py").read_bytes() == (api / "services/events.py").read_bytes()
    assert (here / "redact.py").read_bytes() == (api / "core/redact.py").read_bytes()


def test_an_idle_worker_checks_in_often_enough_for_the_health_checks_to_trust_it(redis_conn):
    """RQ refreshes an idle worker heartbeat every worker_ttl - 15 s; health checks give up after 90 s."""
    from worker.main import WORKER_TTL_SECONDS, build_worker

    worker = build_worker(Queue("hc-idle", connection=redis_conn, serializer=JSONSerializer), redis_conn)
    assert worker.worker_ttl == WORKER_TTL_SECONDS
    assert worker.dequeue_timeout < healthcheck.MAX_HEARTBEAT_AGE_SECONDS
