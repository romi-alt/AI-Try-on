"""Sentry never carries a photo or a secret; PostHog events are anonymous and never block."""

import base64
import io
import json
import uuid
from pathlib import Path

import httpx
import pytest
import sentry_sdk
from PIL import Image
from sentry_sdk.transport import Transport

from app.core import observability
from app.core.config import settings
from app.models import ProductCategory
from app.services import events
from app.services.events import Tracker
from tests.helpers import make_product, make_session


def photo_b64() -> str:
    out = io.BytesIO()
    Image.new("RGB", (240, 320), (200, 120, 90)).save(out, format="JPEG")
    return base64.b64encode(out.getvalue()).decode()


# --- Sentry --------------------------------------------------------------------------------------


def dirty_event(photo: str) -> dict:
    return {
        "message": f"upload failed for data:image/jpeg;base64,{photo}",
        "user": {"ip_address": "203.0.113.9", "id": "u"},
        "request": {
            "url": "https://api.example.com/m/K7TQ4M2X",
            "data": {"file": photo},
            "cookies": {"a": "b"},
            "env": {"REMOTE_ADDR": "203.0.113.9"},
            "query_string": "X-Amz-Signature=abc",
            "headers": {
                "X-Admin-Key": "hunter2",
                "Authorization": "Bearer abc",
                "X-Forwarded-For": "203.0.113.9",
                "Content-Type": "application/json",
            },
        },
        "exception": {
            "values": [
                {
                    "type": "ValueError",
                    "value": f"bad body {photo}",
                    "stacktrace": {"frames": [{"function": "f", "vars": {"image": photo, "n": 1}}]},
                }
            ]
        },
        "extra": {"signed": "https://b/x.webp?X-Amz-Signature=zzz", "raw": b"\x00" * 10},
    }


def test_scrub_event_removes_everything_that_must_not_leave_the_server():
    photo = photo_b64()
    out = observability.scrub_event(dirty_event(photo))
    text = json.dumps(out)
    assert photo[:100] not in text and "/9j/" not in text
    for secret in ("hunter2", "Bearer abc", "203.0.113.9", "zzz", "K7TQ4M2X", "X-Amz-Signature=abc"):
        assert secret not in text, secret
    assert "user" not in out
    assert not {"data", "cookies", "env", "query_string"} & set(out["request"])
    assert out["request"]["headers"] == {"Content-Type": "application/json"}
    assert "vars" not in out["exception"]["values"][0]["stacktrace"]["frames"][0]
    assert out["exception"]["values"][0]["type"] == "ValueError"  # still useful for debugging


class Capture(Transport):
    def __init__(self, options=None):
        super().__init__(options)
        self.events = []

    def capture_envelope(self, envelope):
        for item in envelope.items:
            if item.headers.get("type") == "event":
                self.events.append(item.payload.json)


@pytest.fixture
def sentry(monkeypatch):
    monkeypatch.setattr(settings, "sentry_dsn", "http://public@localhost:9/1")
    transport = Capture()
    assert observability.init_sentry(transport=transport) is True
    yield transport
    sentry_sdk.get_client().close()
    sentry_sdk.init()  # back to disabled


def test_a_real_exception_reaches_the_transport_scrubbed_and_without_locals(sentry):
    photo = photo_b64()

    def process(image):
        raise RuntimeError(f"cannot decode {image[:300]}")

    try:
        process(photo)
    except RuntimeError:
        sentry_sdk.capture_exception()
    sentry_sdk.flush()
    (event,) = sentry.events
    text = json.dumps(event)
    assert photo[:100] not in text and "/9j/" not in text
    frames = event["exception"]["values"][0]["stacktrace"]["frames"]
    assert all("vars" not in f for f in frames)  # no local variables, which hold the image
    assert event["tags"]["service"] == "api"


def test_sentry_is_off_without_a_dsn(monkeypatch):
    monkeypatch.setattr(settings, "sentry_dsn", "")
    assert observability.init_sentry() is False


# --- PostHog -------------------------------------------------------------------------------------


class Posthog:
    """A fake PostHog /batch/ endpoint."""

    def __init__(self, status=200):
        self.status, self.batches, self.requests = status, [], []

    def __call__(self, request: httpx.Request):
        self.requests.append(request)
        self.batches.append(json.loads(request.content))
        return httpx.Response(self.status, json={"status": "Ok"})


def tracker(fake=None, **kw):
    fake = fake or Posthog()
    t = Tracker(
        "phc_test",
        "https://ph.example.com/",
        client=httpx.Client(transport=httpx.MockTransport(fake)),
        autostart=False,
        **kw,
    )
    return t, fake


def test_an_event_is_anonymous_and_carries_only_what_was_given():
    t, fake = tracker()
    sid = uuid.uuid4()
    t.capture("add_to_cart", sid, product_id="p1", category="top", quantity=1, on_sale=True)
    t.flush()
    (batch,) = fake.batches
    assert batch["api_key"] == "phc_test"
    (ev,) = batch["batch"]
    assert ev["event"] == "add_to_cart" and ev["distinct_id"] == str(sid)
    props = ev["properties"]
    assert props["$process_person_profile"] is False and props["$geoip_disable"] is True
    assert {k for k in props if not k.startswith("$")} == {"product_id", "category", "quantity", "on_sale"}
    assert "$ip" not in props and "email" not in props
    assert str(fake.requests[0].url) == "https://ph.example.com/batch/"


def test_only_the_five_known_events_can_be_sent():
    t, _ = tracker()
    with pytest.raises(ValueError):
        t.capture("page_view", "s")
    with pytest.raises(ValueError):
        events.track("surprise", "s")


def test_events_are_sent_in_batches():
    t, fake = tracker()
    for i in range(120):
        t.capture("capture", "s", width=i, height=1)
    while not t._queue.empty():
        t.flush()
    assert [len(b["batch"]) for b in fake.batches] == [50, 50, 20]


def test_a_full_queue_drops_events_instead_of_blocking(monkeypatch):
    monkeypatch.setattr(events, "MAX_QUEUE", 3)
    t, _ = tracker()
    t._queue = __import__("queue").Queue(maxsize=3)
    for _ in range(10):
        t.capture("capture", "s")
    assert t._queue.qsize() == 3 and t.dropped == 7


def test_an_unreachable_or_rejecting_posthog_never_raises(caplog):
    def down(request):
        raise httpx.ConnectError("no route")

    t, _ = tracker(down)
    t.capture("capture", "s")
    t.flush()  # no exception
    t2, _ = tracker(Posthog(status=401))
    t2.capture("capture", "s")
    t2.flush()
    assert {r.message for r in caplog.records} >= {"analytics_unreachable", "analytics_rejected"}


def test_close_sends_what_is_left():
    t, fake = tracker()
    t.capture("capture", "s")
    t.close()
    assert len(fake.batches) == 1


def test_tracking_is_off_without_a_key(monkeypatch):
    assert events.configure("", "https://ph.example.com") is None
    events.track("capture", "s")  # does nothing, does not raise


def test_the_api_and_worker_copies_of_the_tracker_are_identical():
    api = Path(__file__).resolve().parents[1] / "app/services/events.py"
    worker = Path(__file__).resolve().parents[2] / "worker/worker/analytics.py"
    assert api.read_bytes() == worker.read_bytes()


# --- the routes send the right events ------------------------------------------------------------


class Recorder:
    def __init__(self):
        self.sent = []

    def capture(self, event, session_id, **props):
        self.sent.append((event, str(session_id), props))


@pytest.fixture
def recorder(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(events, "_tracker", rec)
    return rec


async def test_session_start_and_add_to_cart_and_request_outfit_events(api, adb, recorder):
    product = await make_product(adb, category=ProductCategory.top, sale_price_pkr=500)
    sid = await make_session(api)
    assert recorder.sent == [("session_start", sid, {})]

    r = await api.post(
        "/cart/add",
        json={"session_id": sid, "product_id": str(product.id), "size": "S", "color": "Ivory", "quantity": 2},
    )
    assert r.status_code == 200
    r = await api.post("/requests", json={"session_id": sid, "product_id": str(product.id), "size": "S"})
    assert r.status_code == 201
    again = await api.post("/requests", json={"session_id": sid, "product_id": str(product.id), "size": "S"})
    assert (
        again.status_code == 200
    )  # a repeat of an open request: staff are not told twice, and neither is analytics

    assert recorder.sent[1:] == [
        (
            "add_to_cart",
            sid,
            {"product_id": str(product.id), "category": "top", "quantity": 2, "on_sale": True},
        ),
        ("request_outfit", sid, {"product_id": str(product.id), "category": "top", "has_size": True}),
    ]


async def test_refused_requests_send_no_events(api, adb, recorder):
    product = await make_product(adb)
    sid = await make_session(api)
    recorder.sent.clear()
    bad = await api.post("/cart/add", json={"session_id": sid, "product_id": str(product.id), "size": "XXXL"})
    assert bad.status_code in (400, 422)
    assert (await api.post("/sessions", json={"consent_given": False})).status_code == 422
    assert recorder.sent == []


async def test_the_capture_event_has_dimensions_and_nothing_identifying(api, adb, s3, recorder):
    from tests.helpers import make_image_bytes

    sid = await make_session(api)
    r = await api.post(
        "/capture",
        data={"session_id": sid},
        files={"file": ("p.jpg", make_image_bytes(900, 1200), "image/jpeg")},
    )
    assert r.status_code == 201, r.text
    ((event, who, props),) = [e for e in recorder.sent if e[0] == "capture"]
    assert who == sid and set(props) == {"width", "height"}
    assert r.json()["key"] not in json.dumps(props)  # the storage key never goes to analytics
