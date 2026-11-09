"""deploy.py against a fake RunPod REST API."""

import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import deploy  # noqa: E402


class FakeRest:
    def __init__(self, templates=(), endpoints=()):
        self.templates = list(templates)
        self.endpoints = list(endpoints)
        self.calls: list[tuple[str, str, dict | None]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.url.scheme == "https" and request.url.host == "rest.runpod.io"
        assert request.headers["authorization"] == "Bearer k"
        body = json.loads(request.content) if request.content else None
        self.calls.append((request.method, request.url.path, body))
        path, method = request.url.path, request.method
        if method == "GET" and path == "/v1/templates":
            return httpx.Response(200, json=self.templates)
        if method == "GET" and path == "/v1/endpoints":
            return httpx.Response(200, json=self.endpoints)
        if method == "POST" and path == "/v1/templates":
            return httpx.Response(200, json={"id": "tpl-new", **body})
        if method == "POST" and path.startswith("/v1/templates/") and path.endswith("/update"):
            return httpx.Response(200, json={"id": path.split("/")[3], **body})
        if method == "POST" and path == "/v1/endpoints":
            return httpx.Response(200, json={"id": "ep-new", **body})
        if method == "PATCH" and path.startswith("/v1/endpoints/"):
            return httpx.Response(200, json={"id": path.split("/")[3], **body})
        return httpx.Response(404, text="nope")


def api(fake):
    return deploy.RunPodApi("k", httpx.Client(transport=httpx.MockTransport(fake)))


def args(*extra):
    return deploy.parse_args(["--image", "reg.example.com/catvton:1", *extra])


def test_dry_run_prints_the_requests_and_sends_nothing():
    out = deploy.deploy(args(), None)
    assert out["endpoint"]["workersMin"] == 0  # scale to zero is the default
    assert (
        out["template"]["imageName"] == "reg.example.com/catvton:1"
        and out["template"]["isServerless"] is True
    )


def test_first_deploy_creates_the_template_then_the_endpoint_scaled_to_zero():
    fake = FakeRest()
    out = deploy.deploy(
        args("--workers-max", "3", "--idle-timeout", "20", "--execution-timeout", "120"),
        api(fake),
    )
    assert [(m, p) for m, p, _ in fake.calls if m == "POST"] == [
        ("POST", "/v1/templates"),
        ("POST", "/v1/endpoints"),
    ]
    ep = fake.calls[-1][2]
    assert ep["templateId"] == "tpl-new" and ep["workersMin"] == 0 and ep["workersMax"] == 3
    assert ep["idleTimeout"] == 20 and ep["executionTimeoutMs"] == 120_000 and ep["computeType"] == "GPU"
    assert out["endpoint_id"] == "ep-new"


def test_running_it_again_updates_instead_of_duplicating():
    fake = FakeRest(
        templates=[{"id": "tpl-1", "name": "elevariq-catvton-template"}],
        endpoints=[{"id": "ep-1", "name": "elevariq-catvton"}],
    )
    out = deploy.deploy(args("--image", "reg.example.com/catvton:2"), api(fake))
    assert ("POST", "/v1/templates/tpl-1/update") in [(m, p) for m, p, _ in fake.calls]
    assert ("PATCH", "/v1/endpoints/ep-1") in [(m, p) for m, p, _ in fake.calls]
    assert not any(p in ("/v1/templates", "/v1/endpoints") and m == "POST" for m, p, _ in fake.calls)
    assert out["endpoint_id"] == "ep-1"
    assert fake.calls[-1][2]["templateId"] == "tpl-1"


def test_an_api_error_is_reported_not_swallowed():
    def refuse(request):
        return httpx.Response(401, text="bad key")

    with pytest.raises(RuntimeError, match="HTTP 401"):
        deploy.deploy(
            args(),
            deploy.RunPodApi("k", httpx.Client(transport=httpx.MockTransport(refuse))),
        )


def test_only_https_is_accepted():
    with pytest.raises(ValueError, match="https"):
        deploy.RunPodApi("k", base_url="http://rest.runpod.io/v1")


def test_workers_max_must_cover_workers_min():
    with pytest.raises(SystemExit):
        args("--workers-min", "3", "--workers-max", "2")
    with pytest.raises(SystemExit):
        args("--workers-max", "0")


def test_the_api_key_is_never_in_the_printed_bodies():
    out = json.dumps(deploy.deploy(args(), None))
    assert "RUNPOD_API_KEY" not in out and "Bearer" not in out
