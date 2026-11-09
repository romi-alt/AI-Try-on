"""FashnProvider against an in-process fake of the FASHN HTTP API (no network, no real key)."""

import base64
import io
import json
import uuid

import httpx
import pytest
from PIL import Image

from tests.helpers import garment_png, webp_bytes
from worker.providers.base import GarmentInput, ProviderError, TryOnRequest
from worker.providers.fashn import API_ERRORS, RUNTIME_ERRORS, FashnProvider

BASE = "https://api.fashn.ai/v1"
KEY = "test-key-not-real"


def jpeg(color) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (864, 1296), color).save(out, format="JPEG")
    return out.getvalue()


class Clock:
    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def __call__(self) -> float:
        return self.now


class FakeFashn:
    """Implements POST /v1/run, GET /v1/status/{id} and a result CDN."""

    def __init__(
        self, *, statuses=("starting", "in_queue", "processing", "completed"), fail=None, run_errors=()
    ):
        self.statuses = list(statuses)
        self.fail = fail  # {"name": ..., "message": ...}
        self.run_errors = list(run_errors)  # httpx.Response factories consumed before succeeding
        self.runs: list[dict] = []
        self.requests: list[httpx.Request] = []
        self.polls: dict[str, int] = {}
        self.outputs: dict[str, bytes] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.method == "POST" and path == "/v1/run":
            if self.run_errors:
                return self.run_errors.pop(0)
            body = json.loads(request.content)
            self.runs.append(body)
            pid = f"pred-{len(self.runs)}"
            self.outputs[pid] = jpeg((40 * len(self.runs) % 256, 80, 120))
            return httpx.Response(200, json={"id": pid, "error": None})
        if request.method == "GET" and path.startswith("/v1/status/"):
            pid = path.rsplit("/", 1)[1]
            n = self.polls[pid] = self.polls.get(pid, 0) + 1
            if self.fail:
                return httpx.Response(200, json={"id": pid, "status": "failed", "error": self.fail})
            status = self.statuses[min(n - 1, len(self.statuses) - 1)]
            body = {"id": pid, "status": status, "error": None}
            if status == "completed":
                body["output"] = [f"https://cdn.fashn.ai/{pid}/output_0.jpg"]
            return httpx.Response(200, json=body)
        if request.method == "GET" and request.url.host == "cdn.fashn.ai":
            pid = path.split("/")[1]
            return httpx.Response(200, content=self.outputs[pid], headers={"content-type": "image/jpeg"})
        return httpx.Response(404, json={"error": "NotFound", "message": path})


def error(status: int, name: str, message="nope", headers=None) -> httpx.Response:
    return httpx.Response(status, json={"error": name, "message": message}, headers=headers)


def provider(fake: FakeFashn, clock: Clock | None = None, **kw) -> FashnProvider:
    clock = clock or Clock()
    return FashnProvider(
        KEY,
        base_url=BASE,
        poll_interval=3.0,
        timeout=60.0,
        client=httpx.Client(transport=httpx.MockTransport(fake)),
        sleep=clock.sleep,
        clock=clock,
        **kw,
    )


def req(*specs) -> TryOnRequest:
    garments = [GarmentInput(uuid.uuid4(), name, cat, garment_png()) for name, cat in specs]
    return TryOnRequest(person_image=webp_bytes(), garments=garments)


def data_uri_bytes(uri: str) -> bytes:
    assert uri.startswith("data:image/jpeg;base64,")
    return base64.b64decode(uri.split(",", 1)[1])


def test_construction_requires_an_api_key(monkeypatch):
    from worker.config import settings

    monkeypatch.setattr(settings, "fashn_api_key", None)
    with pytest.raises(RuntimeError, match="FASHN_API_KEY"):
        FashnProvider()


def test_happy_path_follows_the_documented_flow():
    fake, progress = FakeFashn(), []

    result = provider(fake).run(req(("Linen Shirt", "top")), progress.append)

    run = fake.runs[0]
    assert run["model_name"] == "tryon-v1.6"
    inputs = run["inputs"]
    assert inputs["category"] == "tops" and inputs["mode"] == "balanced" and inputs["num_samples"] == 1
    assert Image.open(io.BytesIO(data_uri_bytes(inputs["model_image"]))).format == "JPEG"
    assert Image.open(io.BytesIO(data_uri_bytes(inputs["garment_image"]))).format == "JPEG"
    methods = [(r.method, r.url.path) for r in fake.requests]
    assert methods[0] == ("POST", "/v1/run")
    assert [m for m in methods if m[1].startswith("/v1/status/")] and methods[-1][1].endswith("output_0.jpg")
    assert result.image == fake.outputs["pred-1"] and result.content_type == "image/jpeg"
    assert progress == sorted(progress) and progress[-1] == 100 and len(set(progress)) > 3


def test_api_key_is_sent_to_fashn_but_not_to_the_result_cdn():
    fake = FakeFashn()
    provider(fake).run(req(("Tee", "top")), lambda p: None)

    for r in fake.requests:
        if r.url.host == "api.fashn.ai":
            assert r.headers["authorization"] == f"Bearer {KEY}"
        else:
            assert "authorization" not in r.headers


def test_polls_at_the_configured_interval_until_completed():
    clock = Clock()
    fake = FakeFashn(statuses=("starting", "in_queue", "processing", "processing", "completed"))

    provider(fake, clock).run(req(("Tee", "top")), lambda p: None)

    assert clock.sleeps == [3.0] * 4


@pytest.mark.parametrize(
    ("our_category", "fashn_category"), [("top", "tops"), ("bottom", "bottoms"), ("dress", "one-pieces")]
)
def test_categories_are_mapped(our_category, fashn_category):
    fake = FakeFashn()
    provider(fake).run(req(("Thing", our_category)), lambda p: None)
    assert fake.runs[0]["inputs"]["category"] == fashn_category


def test_an_outfit_chains_results_one_garment_at_a_time():
    fake, progress = FakeFashn(), []

    result = provider(fake).run(req(("Shirt", "top"), ("Trousers", "bottom")), progress.append)

    assert len(fake.runs) == 2
    assert [r["inputs"]["category"] for r in fake.runs] == ["tops", "bottoms"]
    # The second call dresses the first call's output.
    assert data_uri_bytes(fake.runs[1]["inputs"]["model_image"]) == fake.outputs["pred-1"]
    assert result.image == fake.outputs["pred-2"]
    assert progress == sorted(progress) and progress[-1] == 100
    assert any(40 <= p <= 60 for p in progress)  # the midpoint is the end of garment one


def test_unsupported_categories_fail_before_spending_any_credits():
    fake = FakeFashn()

    with pytest.raises(ProviderError) as e:
        provider(fake).run(req(("Shirt", "top"), ("Red Sneakers", "shoes"), ("Tote", "bag")), lambda p: None)

    assert "Red Sneakers" in e.value.message and "Tote" in e.value.message and "Shirt" not in e.value.message
    assert fake.requests == []


@pytest.mark.parametrize("name", sorted(RUNTIME_ERRORS))
def test_runtime_failures_become_readable_messages(name):
    fake = FakeFashn(fail={"name": name, "message": "model blew up: stack trace 0xdeadbeef"})

    with pytest.raises(ProviderError) as e:
        provider(fake).run(req(("Tee", "top")), lambda p: None)

    assert e.value.message == RUNTIME_ERRORS[name]
    assert "0xdeadbeef" not in e.value.message and name not in e.value.message
    assert "0xdeadbeef" in e.value.detail  # kept for the logs


def test_pose_error_tells_the_shopper_what_to_do():
    fake = FakeFashn(fail={"name": "PoseError", "message": "no pose"})
    with pytest.raises(ProviderError) as e:
        provider(fake).run(req(("Tee", "top")), lambda p: None)
    assert "full body" in e.value.message and "try again" in e.value.message


def test_unknown_runtime_error_is_generic_but_not_silent():
    fake = FakeFashn(fail={"name": "SomethingNew", "message": "weird"})
    with pytest.raises(ProviderError) as e:
        provider(fake).run(req(("Tee", "top")), lambda p: None)
    assert "try again" in e.value.message.lower() and "SomethingNew" in e.value.detail


def test_bad_api_key_is_reported_as_a_setup_problem_without_retrying():
    fake = FakeFashn(run_errors=[error(401, "UnauthorizedAccess", "Unauthorized: Invalid token")])
    with pytest.raises(ProviderError) as e:
        provider(fake).run(req(("Tee", "top")), lambda p: None)
    assert e.value.message == API_ERRORS["UnauthorizedAccess"] and "staff" in e.value.message
    assert len(fake.requests) == 1 and KEY not in e.value.message


def test_out_of_credits_is_not_retried():
    fake = FakeFashn(run_errors=[error(429, "OutOfCredits")])
    with pytest.raises(ProviderError) as e:
        provider(fake).run(req(("Tee", "top")), lambda p: None)
    assert "credits" in e.value.message and len(fake.requests) == 1


def test_rate_limits_are_retried_with_backoff_then_succeed():
    clock = Clock()
    fake = FakeFashn(
        run_errors=[
            error(429, "ConcurrencyLimitExceeded", headers={"retry-after": "5"}),
            error(429, "RateLimitExceeded"),
        ]
    )

    result = provider(fake, clock).run(req(("Tee", "top")), lambda p: None)

    assert result.image == fake.outputs["pred-1"]
    assert clock.sleeps[:2] == [5.0, 4.0]  # honours Retry-After, then exponential backoff


def test_persistent_rate_limiting_gives_up_with_a_busy_message():
    fake = FakeFashn(run_errors=[error(429, "RateLimitExceeded")] * 5)
    with pytest.raises(ProviderError) as e:
        provider(fake).run(req(("Tee", "top")), lambda p: None)
    assert "busy" in e.value.message and len([r for r in fake.requests if r.method == "POST"]) == 3


def test_server_errors_are_retried_then_reported_as_temporary():
    fake = FakeFashn(run_errors=[error(500, "InternalServerError")] * 5)
    with pytest.raises(ProviderError) as e:
        provider(fake).run(req(("Tee", "top")), lambda p: None)
    assert "temporary" in e.value.message and "500" in e.value.detail


def test_network_failure_is_a_readable_error():
    def down(request):
        raise httpx.ConnectError("connection refused")

    p = FashnProvider(
        KEY, base_url=BASE, client=httpx.Client(transport=httpx.MockTransport(down)), sleep=lambda s: None
    )
    with pytest.raises(ProviderError) as e:
        p.run(req(("Tee", "top")), lambda x: None)
    assert "Couldn't reach" in e.value.message


def test_request_timeout_is_a_readable_error():
    def slow(request):
        raise httpx.ReadTimeout("timed out")

    p = FashnProvider(
        KEY, base_url=BASE, client=httpx.Client(transport=httpx.MockTransport(slow)), sleep=lambda s: None
    )
    with pytest.raises(ProviderError) as e:
        p.run(req(("Tee", "top")), lambda x: None)
    assert "took too long" in e.value.message


def test_a_prediction_that_never_finishes_times_out():
    clock = Clock()
    fake = FakeFashn(statuses=("processing",))

    with pytest.raises(ProviderError) as e:
        provider(fake, clock).run(req(("Tee", "top")), lambda p: None)

    assert "took too long" in e.value.message and clock.now > 60


def test_a_few_transient_polling_errors_are_tolerated():
    calls = {"n": 0}
    fake = FakeFashn()

    def flaky(request):
        if request.url.path.startswith("/v1/status/"):
            calls["n"] += 1
            if calls["n"] <= 2:
                return httpx.Response(503)
        return fake(request)

    p = FashnProvider(
        KEY, base_url=BASE, client=httpx.Client(transport=httpx.MockTransport(flaky)), sleep=lambda s: None
    )
    assert p.run(req(("Tee", "top")), lambda x: None).image == fake.outputs["pred-1"]


def test_polling_gives_up_after_repeated_errors():
    def broken(request):
        if request.url.path == "/v1/run":
            return httpx.Response(200, json={"id": "p", "error": None})
        return httpx.Response(503)

    p = FashnProvider(
        KEY, base_url=BASE, client=httpx.Client(transport=httpx.MockTransport(broken)), sleep=lambda s: None
    )
    with pytest.raises(ProviderError) as e:
        p.run(req(("Tee", "top")), lambda x: None)
    assert "Couldn't reach" in e.value.message


def test_flat_lay_transparency_is_flattened_to_white_for_the_api():
    fake = FakeFashn()
    provider(fake).run(req(("Tee", "top")), lambda p: None)
    garment = Image.open(io.BytesIO(data_uri_bytes(fake.runs[0]["inputs"]["garment_image"]))).convert("RGB")
    assert garment.getpixel((2, 2)) == (255, 255, 255)  # transparent corner became white, not black
