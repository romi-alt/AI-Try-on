"""CORS, request IDs and structured logging. None of these touch the database."""

import io
import json
import logging

import pytest

from app.core.config import settings
from app.core.logging import JsonFormatter, request_id_var

KIOSK = "http://localhost:3000"
STRANGER = "https://evil.example"


@pytest.fixture
def json_logs():
    """Capture what the request logger would print, parsed as JSON lines."""
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("app.request")
    logger.addHandler(handler)
    yield lambda: [json.loads(line) for line in buf.getvalue().splitlines()]
    logger.removeHandler(handler)


def test_kiosk_origin_is_configured():
    assert KIOSK in settings.cors_origins
    assert STRANGER not in settings.cors_origins


async def test_cors_preflight_allows_the_kiosk_origin(plain_api):
    r = await plain_api.options(
        "/cart/add",
        headers={
            "Origin": KIOSK,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == KIOSK
    assert "POST" in r.headers["access-control-allow-methods"]
    assert "access-control-allow-credentials" not in r.headers


async def test_cors_preflight_rejects_other_origins(plain_api):
    r = await plain_api.options(
        "/cart/add", headers={"Origin": STRANGER, "Access-Control-Request-Method": "POST"}
    )

    assert "access-control-allow-origin" not in r.headers
    assert r.status_code == 400


async def test_cors_header_is_present_on_real_responses(plain_api):
    ok = await plain_api.get("/health", headers={"Origin": KIOSK})
    other = await plain_api.get("/health", headers={"Origin": STRANGER})

    assert ok.headers["access-control-allow-origin"] == KIOSK
    assert "access-control-allow-origin" not in other.headers
    assert "x-request-id" in ok.headers["access-control-expose-headers"].lower()


async def test_response_carries_a_generated_request_id(plain_api):
    a = await plain_api.get("/health")
    b = await plain_api.get("/health")

    assert a.headers["x-request-id"] and a.headers["x-request-id"] != b.headers["x-request-id"]


async def test_inbound_request_id_is_echoed(plain_api):
    r = await plain_api.get("/health", headers={"X-Request-ID": "trace-123.abc"})
    assert r.headers["x-request-id"] == "trace-123.abc"


async def test_unsafe_request_id_is_replaced(plain_api):
    r = await plain_api.get("/health", headers={"X-Request-ID": "bad id\twith spaces"})
    assert r.headers["x-request-id"] != "bad id\twith spaces"
    assert r.headers["x-request-id"].isalnum()


async def test_each_request_is_logged_as_one_json_line(plain_api, json_logs):
    r = await plain_api.get("/health", headers={"X-Request-ID": "req-1"})

    (line,) = [entry for entry in json_logs() if entry["message"] == "request"]
    assert r.status_code == 200
    assert line["request_id"] == "req-1"
    assert (line["method"], line["path"], line["status"], line["level"]) == ("GET", "/health", 200, "INFO")
    assert line["route"] == "/health"
    assert isinstance(line["duration_ms"], float)
    assert line["logger"] == "app.request" and line["timestamp"].endswith("+00:00")


async def test_client_errors_are_logged_as_warnings(plain_api, json_logs):
    await plain_api.get("/no-such-route")

    (line,) = [entry for entry in json_logs() if entry["message"] == "request"]
    assert (line["status"], line["level"]) == (404, "WARNING")


async def test_unhandled_errors_are_logged_with_traceback_and_status_500(json_logs):
    from app.core.logging import RequestLoggingMiddleware

    async def boom(scope, receive, send):
        raise RuntimeError("kaboom")

    app = RequestLoggingMiddleware(boom)
    sent = []

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "method": "GET", "path": "/boom", "headers": []}
    with pytest.raises(RuntimeError):
        await app(scope, None, send)

    entries = json_logs()
    failure = next(e for e in entries if e["message"] == "unhandled_exception")
    assert "RuntimeError: kaboom" in failure["exception"]
    summary = next(e for e in entries if e["message"] == "request")
    assert (summary["status"], summary["level"]) == (500, "ERROR")
    assert request_id_var.get() is None  # context is cleaned up


def test_json_formatter_includes_extras_and_exceptions():
    formatter = JsonFormatter()
    token = request_id_var.set("rid-9")
    try:
        try:
            raise ValueError("nope")
        except ValueError:
            import sys

            record = logging.LogRecord(
                "x", logging.ERROR, __file__, 1, "failed %s", ("thing",), sys.exc_info()
            )
        record.session_id = "abc"
        out = json.loads(formatter.format(record))
    finally:
        request_id_var.reset(token)

    assert out["message"] == "failed thing"
    assert out["session_id"] == "abc" and out["request_id"] == "rid-9"
    assert "ValueError: nope" in out["exception"]
    for noise in ("args", "msg", "pathname", "levelno", "exc_info"):
        assert noise not in out
