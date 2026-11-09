"""Product analytics events, sent to PostHog from the server.

Events: `session_start`, `capture`, `tryon_done`, `add_to_cart`, `request_outfit`.

Privacy, by construction:
- The distinct id is the *session id*, a random UUID made for one visit. There is no user, no account, no
  name,
  no email, no device id, and `$process_person_profile` is false so PostHog never builds a person.
- GeoIP is switched off (`$geoip_disable`), and the server never forwards a client address.
- Properties are counts, categories, ids of catalog products and timings. Never a picture, a file name, a
  storage
  key or a link.

Sending is fire-and-forget on a background thread with a bounded queue: a slow or unreachable PostHog can
never
slow a request down, an event is dropped rather than retried forever, and nothing here ever raises into a
caller.
Nothing is sent unless `POSTHOG_API_KEY` is set.

This file exists twice, in the API and in the worker (`tryon_done` is sent by the worker, as
`worker/analytics.py`);
a test keeps the two identical.
"""

import atexit
import json
import logging
import queue
import threading
import time
import uuid
from datetime import UTC, datetime

import httpx

logger = logging.getLogger("events")

EVENTS = frozenset({"session_start", "capture", "tryon_done", "add_to_cart", "request_outfit"})
MAX_QUEUE = 1000
BATCH_SIZE = 50
FLUSH_SECONDS = 2.0


class Tracker:
    def __init__(
        self, api_key: str, host: str, *, client: httpx.Client | None = None, autostart: bool = True
    ):
        self.api_key = api_key
        self.url = f"{host.rstrip('/')}/batch/"
        self._http = client or httpx.Client(timeout=5)
        self._queue: queue.Queue[dict] = queue.Queue(maxsize=MAX_QUEUE)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="posthog", daemon=True)
        self.dropped = 0
        if autostart:
            self._thread.start()
            atexit.register(self.close)

    def capture(self, event: str, session_id: uuid.UUID | str, **properties) -> None:
        if event not in EVENTS:
            raise ValueError(f"unknown event {event!r}")  # a typo in our own code, caught in tests
        item = {
            "event": event,
            "distinct_id": str(session_id),
            "properties": {
                **properties,
                "$process_person_profile": False,
                "$geoip_disable": True,
                "$lib": "elevariq-server",
            },
            "timestamp": datetime.now(UTC).isoformat(timespec="milliseconds"),
        }
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            self.dropped += 1  # analytics must never push back on the shop

    def flush(self) -> None:
        batch: list[dict] = []
        while len(batch) < BATCH_SIZE:
            try:
                batch.append(self._queue.get_nowait())
            except queue.Empty:
                break
        if batch:
            self._send(batch)

    def _send(self, batch: list[dict]) -> None:
        try:
            resp = self._http.post(
                self.url,
                content=json.dumps({"api_key": self.api_key, "batch": batch}),
                headers={"Content-Type": "application/json"},
            )
            if resp.status_code >= 400:
                logger.warning("analytics_rejected", extra={"status": resp.status_code, "events": len(batch)})
        except Exception:
            logger.warning("analytics_unreachable", extra={"events": len(batch)})

    def _run(self) -> None:
        while not self._stop.is_set():
            self._stop.wait(FLUSH_SECONDS)
            self.flush()

    def close(self, timeout: float = 3.0) -> None:
        """Send what is queued (up to a few batches) and stop."""
        self._stop.set()
        deadline = time.monotonic() + timeout
        while not self._queue.empty() and time.monotonic() < deadline:
            self.flush()


_tracker: Tracker | None = None
_configured = False


def configure(api_key: str, host: str) -> Tracker | None:
    """Turn tracking on (with a key) or off (without). Called once at start-up."""
    global _tracker, _configured
    _configured = True
    _tracker = Tracker(api_key, host) if api_key else None
    return _tracker


def track(event: str, session_id: uuid.UUID | str, **properties) -> None:
    """Record an event. Safe to call anywhere: it does nothing when tracking is off and never raises."""
    if event not in EVENTS:
        raise ValueError(f"unknown event {event!r}")  # a typo in our own code, caught in tests
    if _tracker is None:
        return
    try:
        _tracker.capture(event, session_id, **properties)
    except Exception:  # pragma: no cover - defensive
        logger.warning("analytics_failed", exc_info=True)
