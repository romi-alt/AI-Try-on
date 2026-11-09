"""Sentry for the worker, set up so that an error report can never carry a shopper's photo or a secret.

Same rules as the API (`app/core/observability.py`): nothing is sent unless `SENTRY_DSN` is set; no local
variables (they hold image bytes), no request data, no personal data; every string goes through
`redact_value`.
"""

import logging
from typing import Any

import sentry_sdk
from sentry_sdk.integrations.rq import RqIntegration

from worker.config import settings
from worker.redact import redact_value

logger = logging.getLogger("worker.observability")


def scrub_event(event: dict[str, Any], hint: dict[str, Any] | None = None) -> dict[str, Any] | None:
    event.pop("user", None)
    request = event.get("request")
    if isinstance(request, dict):
        for field in ("data", "cookies", "env", "query_string", "headers"):
            request.pop(field, None)
    for exc in (event.get("exception") or {}).get("values", []):
        for frame in (exc.get("stacktrace") or {}).get("frames", []):
            frame.pop("vars", None)
    return redact_value(event, truncate=False)


def scrub_breadcrumb(crumb: dict[str, Any], hint: dict[str, Any] | None = None) -> dict[str, Any] | None:
    return redact_value(crumb, truncate=False)


def init_sentry(service: str = "worker", transport=None) -> bool:
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
        integrations=[RqIntegration()],
        before_send=scrub_event,
        before_send_transaction=scrub_event,
        before_breadcrumb=scrub_breadcrumb,
        transport=transport,
    )
    sentry_sdk.set_tag("service", service)
    logger.info("sentry_enabled", extra={"environment": settings.sentry_environment})
    return True
