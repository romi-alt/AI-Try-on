"""No photos, signatures or secrets in log lines or error reports."""

import base64
import io
import json
import logging
from pathlib import Path

from PIL import Image

from app.core.logging import JsonFormatter
from app.core.redact import MAX_FIELD_CHARS, redact_text, redact_value


def jpeg_b64() -> str:
    out = io.BytesIO()
    Image.new("RGB", (240, 320), (200, 120, 90)).save(out, format="JPEG")
    return base64.b64encode(out.getvalue()).decode()


def line(msg, *args, exc=None, **extra) -> dict:
    """What the JSON formatter would print for one log call."""
    record = logging.LogRecord("t", logging.WARNING, __file__, 1, msg, args, exc, None)
    record.__dict__.update(extra)
    return json.loads(JsonFormatter().format(record))


def test_the_api_and_worker_copies_are_identical():
    api = Path(__file__).resolve().parents[1] / "app/core/redact.py"
    worker = Path(__file__).resolve().parents[2] / "worker/worker/redact.py"
    assert api.read_bytes() == worker.read_bytes()


def test_an_encoded_photo_never_survives_in_any_form():
    photo = jpeg_b64()
    assert len(photo) > 500
    for text in (photo, f"data:image/jpeg;base64,{photo}", f'{{"image": "{photo}"}}', f"body={photo[:300]}"):
        out = redact_text(text)
        assert photo[:150] not in out and "/9j/" not in out, out


def test_a_truncated_photo_is_still_caught():
    """Providers sometimes log `str(body)[:300]`: the cut-off blob must not slip under the length
    threshold."""
    photo = jpeg_b64()
    assert "/9j" not in redact_text(f"completed with no image: {{'x': '{photo}'}}"[:300])


def test_short_ordinary_values_are_left_alone():
    text = "job 3f2a9c1e-7b1d-4c55-9a39-2f6d3c1b8e44 status=done pct=100 key=captures/abc/def.webp"
    assert redact_text(text) == text
    assert redact_text("request_id=" + "a" * 32) == "request_id=" + "a" * 32  # a request id is not a blob


def test_presigned_urls_lose_their_signature_but_keep_their_shape():
    url = (
        "https://bucket.example.com/results/s/j.webp?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=AKIA123%2F2026"
        "&X-Amz-Date=20260101T000000Z&X-Amz-Expires=3600&X-Amz-Signature=deadbeefcafe"
    )
    out = redact_text(f"fetching {url}")
    assert "deadbeefcafe" not in out and "AKIA123" not in out
    assert "results/s/j.webp" in out and "X-Amz-Expires=3600" in out


def test_secrets_in_headers_are_removed():
    out = redact_text(
        "headers: Authorization: Bearer abc.def-ghi, X-Admin-Key: hunter2, 'X-Staff-Key': 'sekrit'"
    )
    assert "abc.def-ghi" not in out and "hunter2" not in out and "sekrit" not in out


def test_the_mobile_page_code_is_masked():
    assert redact_text("GET /m/K7TQ4M2X/checkout") == "GET /m/[code]/checkout"
    assert redact_text("/m/%20K7TQ4M2X%20") == "/m/[code]"


def test_bytes_are_replaced_by_their_size_and_nested_values_are_cleaned():
    out = redact_value({"a": b"\xff\xd8" * 100, "b": [jpeg_b64(), {"c": "ok"}], "d": 5})
    assert out["a"] == "<200 bytes>" and out["d"] == 5 and out["b"][1] == {"c": "ok"}
    assert "/9j" not in json.dumps(out)


def test_huge_fields_are_truncated_but_exception_text_is_only_redacted():
    out = redact_value("word " * 2000)
    assert len(out) < MAX_FIELD_CHARS + 100 and "truncated" in out


# --- through the real formatter ------------------------------------------------------------------


def test_the_log_message_and_every_extra_field_are_cleaned():
    photo = jpeg_b64()
    rec = line(
        "upload failed: %s",
        f"data:image/jpeg;base64,{photo}",
        file=photo,
        raw=b"\x00" * 10,
        url="https://x/y.webp?X-Amz-Signature=zzz",
        nested={"img": photo},
    )
    dumped = json.dumps(rec)
    assert photo[:100] not in dumped and "zzz" not in dumped
    assert rec["raw"] == "<10 bytes>"


def test_an_exception_that_contains_a_photo_is_cleaned_in_the_stack_trace():
    photo = jpeg_b64()
    try:
        raise ValueError(f"bad response body: {photo}")
    except ValueError:
        import sys

        rec = line("boom", exc=sys.exc_info())
    assert photo[:100] not in rec["exception"] and "ValueError" in rec["exception"]


def test_the_request_log_masks_mobile_codes(caplog):
    from app.core.logging import RequestLoggingMiddleware

    seen = []

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 404, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def run():
        async def receive():
            return {"type": "http.request", "body": b""}

        async def send(message):
            seen.append(message)

        await RequestLoggingMiddleware(app)(
            {"type": "http", "method": "GET", "path": "/m/K7TQ4M2X", "headers": []}, receive, send
        )

    import asyncio

    with caplog.at_level(logging.INFO, logger="app.request"):
        asyncio.run(run())
    paths = [r.path for r in caplog.records if hasattr(r, "path")]
    assert paths == ["/m/[code]"]
