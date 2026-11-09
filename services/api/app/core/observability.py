"""Sentry for the API, set up so that an error report can never carry a shopper's photo or a secret.

Nothing is sent unless `SENTRY_DSN` is set. Even then:

- no request bodies (`max_request_body_size="never"`), no cookies, no personal data
  (`send_default_pii=False`);
- no local variables in stack frames (they can hold image bytes);
- every string in every event goes through `redact_value` (photos, signed URLs, keys, mobile codes);
- the client's address and the proxy headers are removed.
"""

import logging
from typing import Any

import sentry_sdk

from app.core.config import settings
from app.core.redact import redact_value

logger = logging.getLogger("app.observability")

_DROP_HEADERS = {
    "authorization",
    "cookie",
    "set-cookie",
    "x-admin-key",
    "x-staff-key",
    "x-forwarded-for",
    "x-real-ip",
    "forwarded",
}


def scrub_event(event: dict[str, Any], hint: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """The `before_send` hook: strips everything that must not leave the server."""
    request = event.get("request")
    if isinstance(request, dict):
        for field in ("data", "cookies", "env", "query_string"):
            request.pop(field, None)
        headers = request.get("headers")
        if isinstance(headers, dict):
            request["headers"] = {k: v for k, v in headers.items() if k.lower() not in _DROP_HEADERS}
    event.pop("user", None)
    for exc in (event.get("exception") or {}).get("values", []):
        for frame in (exc.get("stacktrace") or {}).get("frames", []):
            frame.pop("vars", None)
    return redact_value(event, truncate=False)


def scrub_breadcrumb(crumb: dict[str, Any], hint: dict[str, Any] | None = None) -> dict[str, Any] | None:
    return redact_value(crumb, truncate=False)


def init_sentry(transport=None) -> bool:
    """Start Sentry if a DSN is configured. Returns whether it is on. `transport` is for tests."""
    if not settings.sentry_dsn:
        return False
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.sentry_environment,
        release=settings.sentry_release or None,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        send_default_pii=False,
        include_local_variables=False,
        max_request_body_size="never",
        before_send=scrub_event,
        before_send_transaction=scrub_event,
        before_breadcrumb=scrub_breadcrumb,
        transport=transport,
    )
    sentry_sdk.set_tag("service", "api")
    logger.info("sentry_enabled", extra={"environment": settings.sentry_environment})
    return True
