"""Keeps pictures, links with signatures and secrets out of logs (and error reports).

Photos of shoppers are the one thing this system must never leak into a log line or an error tracker. The
code does
not log them on purpose; this is the net underneath, for the day a library puts a request body in an exception
message or someone logs a whole response. It is applied by the JSON log formatter and by the Sentry
`before_send`
hook (`app/core/observability.py`, `worker/observability.py`). This file exists twice, in the API and in the
worker, and a test keeps the two identical.

What it removes:
- `data:image/...;base64,...` URIs and any long run of base64-looking characters (an encoded image is far
  longer
  than anything that should appear in a log line);
- the signature, credential and token parts of presigned storage URLs (the rest of the URL stays, for
  debugging);
- `Authorization: Bearer ...` and `X-Admin-Key` / `X-Staff-Key` values;
- the code in `/m/CODE` mobile-page paths (it is a bearer credential for 24 hours);
- raw `bytes` values, which are replaced by their size.
"""

import re
from typing import Any

MAX_FIELD_CHARS = 2000
_BLOB = re.compile(r"[A-Za-z0-9+/_\-]{120,}={0,2}")
_DATA_URI = re.compile(r"data:[\w/+.-]+;base64,[A-Za-z0-9+/_\-=]*", re.IGNORECASE)
_SIGNED_QUERY = re.compile(
    r"([?&])(X-Amz-Signature|X-Amz-Credential|X-Amz-Security-Token|Signature|AWSAccessKeyId)=[^&\s\"'<>]+",
    re.IGNORECASE,
)
_BEARER = re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
_KEY_HEADER = re.compile(r"(X-(?:Admin|Staff)-Key['\"]?\s*[:=]\s*['\"]?)[^'\",\s}]+", re.IGNORECASE)
_MOBILE_CODE = re.compile(r"(/m/)[A-Za-z0-9%]{4,20}")


def redact_text(text: str) -> str:
    text = _DATA_URI.sub("data:[image removed]", text)
    text = _SIGNED_QUERY.sub(r"\1\2=[redacted]", text)
    text = _BEARER.sub(r"\1[redacted]", text)
    text = _KEY_HEADER.sub(r"\1[redacted]", text)
    text = _MOBILE_CODE.sub(r"\1[code]", text)
    return _BLOB.sub("[blob removed]", text)


def redact_value(value: Any, *, truncate: bool = True) -> Any:
    """Redact strings anywhere inside `value` (dicts, lists, tuples); `bytes` become a size note."""
    if isinstance(value, str):
        out = redact_text(value)
        if truncate and len(out) > MAX_FIELD_CHARS:
            out = f"{out[:MAX_FIELD_CHARS]}...[truncated {len(out) - MAX_FIELD_CHARS} characters]"
        return out
    if isinstance(value, bytes | bytearray | memoryview):
        return f"<{len(value)} bytes>"
    if isinstance(value, dict):
        return {k: redact_value(v, truncate=truncate) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [redact_value(v, truncate=truncate) for v in value]
    return value
