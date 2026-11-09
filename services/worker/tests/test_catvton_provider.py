"""CatVTONProvider against an in-process fake of the RunPod serverless HTTP API (no network, GPU or key)."""

import base64
import io
import json
import uuid

import httpx
import pytest
from PIL import Image

from tests.helpers import garment_png, webp_bytes
from worker.providers import get_provider
from worker.providers.base import GarmentInput, ProviderError, TryOnRequest
from worker.providers.catvton import HANDLER_ERRORS, CatVTONProvider

BASE = "https://api.runpod.ai/v2"
ENDPOINT = "ep123"
KEY = "test-key-not-real"


def png_of(size) -> bytes:
    out = io.BytesIO()
    Image.new("RGBA", size, (200, 30, 60, 255)).save(out, format="PNG")
    return out.getvalue()


def result_jpeg(size=(768, 1024), color=(120, 90, 200)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, format="JPEG")
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


class FakeRunPod:
    """POST /run, GET /status/{id}, POST /cancel/{id}. `script` is the status bodies served in turn."""

    def __init__(self, script=None, run_errors=()):
        self.script = list(script) if script is not None else None
        self.run_errors = list(run_errors)
        self.runs: list[dict] = []
        self.requests: list[httpx.Request] = []
        self.cancelled: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        assert request.headers["authorization"] == f"Bearer {KEY}"
        if request.method == "POST" and path == f"/v2/{ENDPOINT}/run":
            if self.run_errors:
                return self.run_errors.pop(0)
            self.runs.append(json.loads(request.content))
            return httpx.Response(200, json={"id": "job-1", "status": "IN_QUEUE"})
        if request.method == "POST" and path.startswith(f"/v2/{ENDPOINT}/cancel/"):
            self.cancelled.append(path.rsplit("/", 1)[1])
            return httpx.Response(200, json={"status": "CANCELLED"})
        if request.method == "GET" and path == f"/v2/{ENDPOINT}/status/job-1":
            item = self.script.pop(0) if len(self.script) > 1 else self.script[0]
            if isinstance(item, Exception):
                raise item
            if isinstance(item, httpx.Response):
                return item
            return httpx.Response(200, json=item)
        return httpx.Response(404, json={"error": f"unexpected {request.method} {path}"})


def completed(image: bytes | None = None, **extra) -> dict:
    return {
        "status": "COMPLETED",
        "output": {"image": base64.b64encode(image or result_jpeg()).decode(), "content_type": "image/jpeg"},
        **extra,
    }


def provider(fake: FakeRunPod, clock: Clock | None = None, **kw) -> tuple[CatVTONProvider, Clock]:
    clock = clock or Clock()
    p = CatVTONProvider(
        KEY,
        ENDPOINT,
        base_url=BASE,
        poll_interval=2.0,
        timeout=kw.pop("timeout", 420.0),
        client=httpx.Client(transport=httpx.MockTransport(fake)),
        sleep=clock.sleep,
        clock=clock,
        **kw,
    )
    return p, clock


def req(*categories, person_size=(864, 1296)) -> TryOnRequest:
    garments = [GarmentInput(uuid.uuid4(), f"Item {i}", c, garment_png()) for i, c in enumerate(categories)]
    return TryOnRequest(person_image=webp_bytes(*person_size), garments=garments)


def run(p, request, progress=None):
    return p.run(request, (progress if progress is not None else []).append)


# --- the happy path ------------------------------------------------------------------------------


def test_sends_the_outfit_in_one_request_and_returns_the_result():
    fake = FakeRunPod(
        [{"status": "IN_QUEUE"}, {"status": "IN_PROGRESS"}, completed(executionTime=9500, delayTime=1200)]
    )
    p, _ = provider(fake, steps=25, guidance_scale=3.0, seed=7)
    progress: list[int] = []

    result = p.run(req("top", "bottom"), progress.append)

    assert len(fake.runs) == 1  # the whole outfit is one job, the GPU worker does the chaining
    sent = fake.runs[0]["input"]
    assert [g["category"] for g in sent["garments"]] == ["top", "bottom"]
    assert (sent["steps"], sent["guidance_scale"], sent["seed"]) == (25, 3.0, 7)
    for blob in (sent["person_image"], *[g["image"] for g in sent["garments"]]):
        assert Image.open(io.BytesIO(base64.b64decode(blob))).format == "JPEG"
    assert Image.open(io.BytesIO(result.image)).size == (768, 1024)
    assert result.content_type == "image/jpeg"
    assert progress == sorted(progress) and progress[-1] == 100 and progress[0] >= 1
    assert p.last_metrics.execution_ms == 9500 and p.last_metrics.delay_ms == 1200
    assert p.last_metrics.wall_seconds > 0


def test_calls_only_the_configured_https_endpoint():
    fake = FakeRunPod([completed()])
    p, _ = provider(fake)
    run(p, req("top"))
    assert {r.url.host for r in fake.requests} == {"api.runpod.ai"}
    assert all(r.url.scheme == "https" for r in fake.requests)


def test_large_images_are_scaled_down_before_sending():
    fake = FakeRunPod([completed()])
    p, _ = provider(fake)
    big = TryOnRequest(
        person_image=webp_bytes(4000, 6000),
        garments=[GarmentInput(uuid.uuid4(), "Top", "top", png_of((3000, 3000)))],
    )
    run(p, big)
    sent = fake.runs[0]["input"]
    person = Image.open(io.BytesIO(base64.b64decode(sent["person_image"])))
    garment = Image.open(io.BytesIO(base64.b64decode(sent["garments"][0]["image"])))
    assert max(person.size) == 2048 and max(garment.size) == 1536


def test_an_unsupported_category_is_refused_before_any_request():
    fake = FakeRunPod([completed()])
    p, _ = provider(fake)
    with pytest.raises(ProviderError, match="tops, bottoms and dresses only") as e:
        run(p, req("top", "shoes"))
    assert "Item 1" in e.value.message
    assert fake.requests == []


# --- progress ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "output",
    [{"progress": 40}, json.dumps({"progress": 40}), "40%", " 40 % ".strip()],
)
def test_running_progress_comes_from_the_handlers_step_report(output):
    fake = FakeRunPod([{"status": "IN_PROGRESS", "output": output}, completed()])
    p, _ = provider(fake)
    progress: list[int] = []
    run(p, req("top"), progress)
    assert 40 in progress


def test_queued_stays_low_and_running_without_a_report_does_not_stall_or_jump():
    fake = FakeRunPod([{"status": "IN_QUEUE"}] * 30 + [{"status": "IN_PROGRESS"}] * 3 + [completed()])
    p, _ = provider(fake)
    progress: list[int] = []
    run(p, req("top"), progress)
    queued = [v for v in progress if v < 6]
    assert queued and max(queued) <= 5
    assert progress == sorted(progress) and len(set(progress)) == len(progress)  # no repeats, never backwards
    assert progress[-2:] == [6, 100]


def test_progress_never_goes_backwards_and_is_capped_below_done():
    fake = FakeRunPod(
        [
            {"status": "IN_PROGRESS", "output": {"progress": 70}},
            {"status": "IN_PROGRESS", "output": {"progress": 30}},  # a stale or reordered report
            {"status": "IN_PROGRESS", "output": {"progress": 250}},
            completed(),
        ]
    )
    p, _ = provider(fake)
    progress: list[int] = []
    run(p, req("top"), progress)
    assert progress == [1, 70, 99, 100]


# --- submitting ----------------------------------------------------------------------------------


def test_run_is_retried_on_429_and_5xx_then_succeeds():
    fake = FakeRunPod(
        [completed()],
        run_errors=[httpx.Response(429, headers={"retry-after": "3"}), httpx.Response(503)],
    )
    p, clock = provider(fake)
    run(p, req("top"))
    assert len(fake.runs) == 1
    assert clock.sleeps[:2] == [3.0, 4.0]  # retry-after honoured, then exponential


def test_run_gives_up_after_three_attempts():
    fake = FakeRunPod([completed()], run_errors=[httpx.Response(502)] * 3)
    p, _ = provider(fake)
    with pytest.raises(ProviderError, match="temporary problem"):
        run(p, req("top"))
    assert fake.runs == []


def test_a_busy_endpoint_says_busy():
    fake = FakeRunPod([completed()], run_errors=[httpx.Response(429)] * 3)
    p, _ = provider(fake)
    with pytest.raises(ProviderError, match="very busy"):
        run(p, req("top"))


@pytest.mark.parametrize("status", [401, 403])
def test_a_rejected_key_is_a_setup_problem_and_is_not_retried(status):
    fake = FakeRunPod([completed()], run_errors=[httpx.Response(status, text="bad key")])
    p, _ = provider(fake)
    with pytest.raises(ProviderError, match="isn't set up correctly") as e:
        run(p, req("top"))
    assert len(fake.requests) == 1 and KEY not in (e.value.detail or "")


def test_an_unreachable_service_is_reported():
    def boom(request):
        raise httpx.ConnectError("no route")

    clock = Clock()
    p = CatVTONProvider(
        KEY,
        ENDPOINT,
        base_url=BASE,
        client=httpx.Client(transport=httpx.MockTransport(boom)),
        sleep=clock.sleep,
        clock=clock,
    )
    with pytest.raises(ProviderError, match="Couldn't reach"):
        run(p, req("top"))


def test_a_run_response_without_an_id_is_an_error():
    class NoId(FakeRunPod):
        def __call__(self, request):
            if request.method == "POST" and request.url.path.endswith("/run"):
                return httpx.Response(200, json={"status": "IN_QUEUE"})
            return super().__call__(request)

    p, _ = provider(NoId([completed()]))
    with pytest.raises(ProviderError, match="temporary problem"):
        run(p, req("top"))


# --- following the job ---------------------------------------------------------------------------


def test_transient_polling_errors_are_ridden_out():
    fake = FakeRunPod(
        [httpx.ConnectError("blip"), httpx.Response(502), {"status": "IN_PROGRESS"}, completed()]
    )
    p, _ = provider(fake)
    assert run(p, req("top")).image


def test_repeated_polling_errors_give_up():
    fake = FakeRunPod([httpx.ConnectError("down")])
    p, _ = provider(fake)
    with pytest.raises(ProviderError, match="Couldn't reach"):
        run(p, req("top"))
    assert fake.cancelled == ["job-1"]


def test_a_key_revoked_mid_job_is_a_setup_problem():
    fake = FakeRunPod([httpx.Response(401)])
    p, _ = provider(fake)
    with pytest.raises(ProviderError, match="isn't set up correctly"):
        run(p, req("top"))


def test_a_job_that_never_finishes_times_out_and_is_cancelled():
    fake = FakeRunPod([{"status": "IN_QUEUE"}])
    p, clock = provider(fake, timeout=60.0)
    with pytest.raises(ProviderError, match="took too long"):
        run(p, req("top"))
    assert fake.cancelled == ["job-1"]  # so the GPU is not billed for a result nobody wants
    assert 60 <= clock.now < 70


@pytest.mark.parametrize(
    ("status", "message"), [("TIMED_OUT", "took too long"), ("CANCELLED", "temporary problem")]
)
def test_terminal_non_success_statuses(status, message):
    fake = FakeRunPod([{"status": status}])
    p, _ = provider(fake)
    with pytest.raises(ProviderError, match=message):
        run(p, req("top"))


def test_an_unknown_status_is_an_error():
    fake = FakeRunPod([{"status": "WEIRD"}])
    p, _ = provider(fake)
    with pytest.raises(ProviderError, match="temporary problem"):
        run(p, req("top"))


# --- failures reported by the GPU handler ------------------------------------------------------


@pytest.mark.parametrize("code", sorted(HANDLER_ERRORS))
def test_handler_error_codes_map_to_shopper_messages(code):
    fake = FakeRunPod([{"status": "FAILED", "error": json.dumps({"code": code, "message": "details here"})}])
    p, _ = provider(fake)
    with pytest.raises(ProviderError) as e:
        run(p, req("top"))
    assert e.value.message == HANDLER_ERRORS[code]
    assert code in e.value.detail and "details here" in e.value.detail  # the specifics stay in the logs


def test_an_unstructured_failure_is_generic_and_does_not_leak_a_traceback():
    fake = FakeRunPod([{"status": "FAILED", "error": "Traceback (most recent call last):\n  File secret.py"}])
    p, _ = provider(fake)
    with pytest.raises(ProviderError) as e:
        run(p, req("top"))
    assert e.value.message == "The try-on service had a temporary problem. Please try again."
    assert "Traceback" not in e.value.message


@pytest.mark.parametrize(
    "bad",
    [
        {"status": "COMPLETED", "output": None},
        {"status": "COMPLETED", "output": {}},
        {"status": "COMPLETED", "output": {"image": "!!!not base64!!!"}},
        {"status": "COMPLETED", "output": {"image": base64.b64encode(b"not an image").decode()}},
    ],
)
def test_a_missing_or_unreadable_result_is_an_error(bad):
    p, _ = provider(FakeRunPod([bad]))
    with pytest.raises(ProviderError, match="temporary problem"):
        run(p, req("top"))


def test_an_unexpected_result_size_is_still_returned():
    p, _ = provider(FakeRunPod([completed(result_jpeg((512, 512)))]))
    assert Image.open(io.BytesIO(run(p, req("top")).image)).size == (512, 512)


# --- setup ---------------------------------------------------------------------------------------


def test_needs_a_key_and_an_endpoint():
    with pytest.raises(RuntimeError, match="RUNPOD_API_KEY and RUNPOD_ENDPOINT_ID"):
        CatVTONProvider("", ENDPOINT)
    with pytest.raises(RuntimeError, match="RUNPOD_API_KEY and RUNPOD_ENDPOINT_ID"):
        CatVTONProvider(KEY, "")


def test_refuses_a_plain_http_base_url():
    with pytest.raises(RuntimeError, match="https"):
        CatVTONProvider(KEY, ENDPOINT, base_url="http://api.runpod.ai/v2")


def test_the_factory_builds_it_from_settings(monkeypatch):
    from worker.config import settings

    monkeypatch.setattr(settings, "tryon_provider", "catvton")
    monkeypatch.setattr(settings, "runpod_api_key", KEY)
    monkeypatch.setattr(settings, "runpod_endpoint_id", ENDPOINT)
    p = get_provider()
    assert isinstance(p, CatVTONProvider) and p.endpoint == f"{BASE}/{ENDPOINT}"
