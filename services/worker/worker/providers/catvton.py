"""CatVTON virtual try-on, served from a RunPod serverless endpoint (see `services/catvton`).

The GPU side runs in its own container (CatVTON loaded once per worker, scale to zero when idle). This
provider is the client: it sends the whole outfit in one request, follows the job to the end and returns the
768x1024 result.

    POST {base}/{endpoint}/run          {"input": {...}}  -> {"id", "status": "IN_QUEUE"}
    GET  {base}/{endpoint}/status/{id}  -> {"status", "output", "error", "delayTime", "executionTime"}
    POST {base}/{endpoint}/cancel/{id}  (when we give up, so the GPU stops being billed)

The input/output contract is documented in `services/catvton/README.md` and implemented by its handler.

Every failure becomes a ProviderError with a message that is fit to show a shopper; the technical detail goes
to the logs.
"""

import base64
import binascii
import io
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx
from PIL import Image, UnidentifiedImageError

from worker.config import settings
from worker.providers.base import ProgressFn, ProviderError, TryOnProvider, TryOnRequest, TryOnResult
from worker.providers.imaging import sniff_content_type, to_jpeg

logger = logging.getLogger("worker.catvton")

# CatVTON dresses one region per pass: upper body, lower body, or the whole body.
SUPPORTED_CATEGORIES = ("top", "bottom", "dress")
RESULT_SIZE = (768, 1024)  # width, height
RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_RUN_ATTEMPTS = 3
MAX_POLL_ERRORS = 4
# RunPod refuses /run bodies above 10 MB; leave room for the JSON around the images.
MAX_BODY_BYTES = 9 * 1024 * 1024
PERSON_MAX_SIDE = 2048
GARMENT_MAX_SIDE = 1536

TEMPORARY = "The try-on service had a temporary problem. Please try again."
BUSY = "The try-on service is very busy right now. Please try again in a moment."
UNREACHABLE = "Couldn't reach the try-on service. Please try again."
TOO_SLOW = "The try-on service took too long. Please try again."
MISCONFIGURED = "The try-on service isn't set up correctly. Please ask staff for help."

# Codes the GPU handler puts in its error (see services/catvton/handler.py) -> what the shopper sees.
HANDLER_ERRORS = {
    "no_person": "We couldn't see you clearly. Stand back so you're fully in frame and try again.",
    "bad_image": "The try-on service couldn't read the photo or the garment image.",
    "unsupported_category": "Virtual try-on works for tops, bottoms and dresses only.",
    "out_of_memory": TEMPORARY,
    "internal": TEMPORARY,
}


@dataclass(frozen=True)
class RunMetrics:
    """What RunPod reported for the last job, for the benchmark. Milliseconds, as RunPod gives them."""

    wall_seconds: float
    execution_ms: int | None
    delay_ms: int | None  # time in the queue, including a cold start


class CatVTONProvider(TryOnProvider):
    name = "catvton"

    def __init__(
        self,
        api_key: str | None = None,
        endpoint_id: str | None = None,
        *,
        base_url: str | None = None,
        poll_interval: float | None = None,
        timeout: float | None = None,
        steps: int | None = None,
        guidance_scale: float | None = None,
        seed: int | None = None,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.api_key = api_key if api_key is not None else settings.runpod_api_key
        self.endpoint_id = endpoint_id if endpoint_id is not None else settings.runpod_endpoint_id
        if not self.api_key or not self.endpoint_id:
            raise RuntimeError(
                "TRYON_PROVIDER=catvton requires RUNPOD_API_KEY and RUNPOD_ENDPOINT_ID to be set"
            )
        base = (base_url or settings.runpod_base_url).rstrip("/")
        if not base.startswith("https://") and not _is_local(base):
            raise RuntimeError("RUNPOD_BASE_URL must be an https:// address")
        self.endpoint = f"{base}/{self.endpoint_id}"
        self.poll_interval = (
            settings.catvton_poll_interval_seconds if poll_interval is None else poll_interval
        )
        self.timeout = settings.catvton_timeout_seconds if timeout is None else timeout
        self.steps = settings.catvton_steps if steps is None else steps
        self.guidance_scale = settings.catvton_guidance_scale if guidance_scale is None else guidance_scale
        self.seed = settings.catvton_seed if seed is None else seed
        self._http = client or httpx.Client(timeout=30)
        self._sleep = sleep
        self._clock = clock
        self.last_metrics: RunMetrics | None = None

    # --- public ----------------------------------------------------------------------------

    def run(self, request: TryOnRequest, on_progress: ProgressFn) -> TryOnResult:
        unsupported = [g.name for g in request.garments if g.category not in SUPPORTED_CATEGORIES]
        if unsupported:
            raise ProviderError(
                "Virtual try-on works for tops, bottoms and dresses only. "
                f"Please remove: {', '.join(unsupported)}."
            )
        payload = self._payload(request)

        started = self._clock()
        on_progress(1)
        job_id = self._submit(payload)
        try:
            output, status_body = self._wait(job_id, started, on_progress)
        except ProviderError:
            self._cancel(job_id)
            raise
        result = self._decode(output)
        self.last_metrics = RunMetrics(
            wall_seconds=self._clock() - started,
            execution_ms=_int_or_none(status_body.get("executionTime")),
            delay_ms=_int_or_none(status_body.get("delayTime")),
        )
        logger.info(
            "catvton_done",
            extra={
                "job": job_id,
                "wall_seconds": round(self.last_metrics.wall_seconds, 1),
                "execution_ms": self.last_metrics.execution_ms,
                "delay_ms": self.last_metrics.delay_ms,
            },
        )
        on_progress(100)
        return result

    # --- request ---------------------------------------------------------------------------

    def _payload(self, request: TryOnRequest) -> dict:
        body = {
            "input": {
                "person_image": _b64(to_jpeg(request.person_image, max_side=PERSON_MAX_SIDE)),
                "garments": [
                    {"category": g.category, "image": _b64(to_jpeg(g.image, max_side=GARMENT_MAX_SIDE))}
                    for g in request.garments
                ],
                "steps": self.steps,
                "guidance_scale": self.guidance_scale,
                "seed": self.seed,
            }
        }
        size = len(json.dumps(body))
        if size > MAX_BODY_BYTES:
            raise ProviderError(
                TEMPORARY, detail=f"request body {size} bytes exceeds the {MAX_BODY_BYTES} limit"
            )
        return body

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _submit(self, payload: dict) -> str:
        for attempt in range(1, MAX_RUN_ATTEMPTS + 1):
            try:
                resp = self._http.post(f"{self.endpoint}/run", json=payload, headers=self._headers())
            except httpx.TimeoutException as e:
                raise ProviderError(TOO_SLOW, detail=f"POST /run timed out: {e}") from e
            except httpx.TransportError as e:
                raise ProviderError(UNREACHABLE, detail=f"POST /run failed: {e!r}") from e

            if resp.status_code == 200:
                body = _json(resp)
                if not body.get("id"):
                    raise ProviderError(TEMPORARY, detail=f"unexpected /run response: {body}")
                return str(body["id"])
            logger.warning(
                "catvton_run_rejected", extra={"http_status": resp.status_code, "attempt": attempt}
            )
            if resp.status_code in (401, 403):
                raise ProviderError(MISCONFIGURED, detail=f"{resp.status_code}: {resp.text[:200]}")
            if resp.status_code in RETRY_STATUSES and attempt < MAX_RUN_ATTEMPTS:
                self._sleep(_retry_delay(resp, attempt))
                continue
            raise ProviderError(
                BUSY if resp.status_code == 429 else TEMPORARY,
                detail=f"{resp.status_code}: {resp.text[:200]}",
            )
        raise AssertionError("unreachable")  # pragma: no cover

    # --- following the job -----------------------------------------------------------------

    def _wait(self, job_id: str, started: float, on_progress: ProgressFn) -> tuple[dict, dict]:
        errors = 0
        last = 1
        while True:
            elapsed = self._clock() - started
            if elapsed > self.timeout:
                raise ProviderError(TOO_SLOW, detail=f"job {job_id} not done after {elapsed:.0f}s")
            try:
                resp = self._http.get(f"{self.endpoint}/status/{job_id}", headers=self._headers())
                resp.raise_for_status()
                body = _json(resp)
                errors = 0
            except (httpx.TransportError, httpx.HTTPStatusError) as e:
                if isinstance(e, httpx.HTTPStatusError) and e.response.status_code in (401, 403):
                    raise ProviderError(MISCONFIGURED, detail=f"status {e.response.status_code}") from e
                errors += 1
                if errors >= MAX_POLL_ERRORS:
                    raise ProviderError(UNREACHABLE, detail=f"status polling failed {errors}x: {e!r}") from e
                self._sleep(self.poll_interval)
                continue

            status = body.get("status")
            if status == "COMPLETED":
                output = body.get("output")
                if not isinstance(output, dict) or not output.get("image"):
                    raise ProviderError(TEMPORARY, detail=f"completed with no image: {str(body)[:300]}")
                return output, body
            if status == "FAILED":
                raise _failure(body)
            if status in ("CANCELLED", "TIMED_OUT"):
                raise ProviderError(TOO_SLOW if status == "TIMED_OUT" else TEMPORARY, detail=f"job {status}")
            if status not in ("IN_QUEUE", "IN_PROGRESS"):
                raise ProviderError(TEMPORARY, detail=f"unknown status {status!r}")

            pct = self._progress(status, body, elapsed)
            if pct > last:  # never backwards
                last = pct
                on_progress(pct)
            self._sleep(self.poll_interval)

    def _progress(self, status: str, body: dict, elapsed: float) -> int:
        """0-99. Queued (or a worker still starting) stays low; running uses the handler's step progress."""
        if status == "IN_QUEUE":
            return min(
                5, 1 + int(elapsed / 10)
            )  # a slow creep so the screen is visibly alive during a cold start
        reported = _reported_progress(body.get("output"))
        if reported is not None:
            return max(6, min(99, reported))
        return 6  # running, but no step information (older handler or RunPod not exposing it)

    def _cancel(self, job_id: str) -> None:
        try:
            self._http.post(f"{self.endpoint}/cancel/{job_id}", headers=self._headers(), timeout=10)
        except Exception:  # best effort: the job's own execution timeout is the backstop
            logger.warning("catvton_cancel_failed", extra={"job": job_id})

    # --- result ----------------------------------------------------------------------------

    def _decode(self, output: dict) -> TryOnResult:
        try:
            data = base64.b64decode(output["image"], validate=True)
            img = Image.open(io.BytesIO(data))
            img.load()
        except (binascii.Error, ValueError, UnidentifiedImageError, OSError) as e:
            raise ProviderError(TEMPORARY, detail=f"result image unreadable: {e!r}") from e
        if img.size != RESULT_SIZE:
            logger.warning(
                "catvton_unexpected_size", extra={"size": list(img.size), "expected": list(RESULT_SIZE)}
            )
        return TryOnResult(image=data, content_type=sniff_content_type(data))


# --- helpers -------------------------------------------------------------------------------


def _is_local(base: str) -> bool:
    return base.startswith(("http://127.0.0.1", "http://localhost"))  # the fake server in tests


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _json(resp: httpx.Response) -> dict:
    try:
        body = resp.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _int_or_none(value) -> int | None:
    return int(value) if isinstance(value, int | float) else None


def _retry_delay(resp: httpx.Response, attempt: int) -> float:
    try:
        return min(float(resp.headers["retry-after"]), 30.0)
    except (KeyError, ValueError):
        return float(2**attempt)


def _reported_progress(output) -> int | None:
    """Step progress from a running job's `output`: `{"progress": 40}`, a JSON string of that, or `"40%"`."""
    if isinstance(output, str):
        text = output.strip()
        if text.endswith("%") and text[:-1].strip().isdigit():
            return int(text[:-1])
        try:
            output = json.loads(text)
        except ValueError:
            return None
    if isinstance(output, dict):
        value = output.get("progress")
        if isinstance(value, int | float) and not isinstance(value, bool):
            return round(value)
    return None


def _failure(body: dict) -> ProviderError:
    """The handler puts `{"code", "message"}` as a JSON string in `error`; anything else is generic."""
    raw = body.get("error")
    code = message = ""
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                code, message = str(parsed.get("code", "")), str(parsed.get("message", ""))
        except ValueError:
            message = raw[:300]
    logger.warning("catvton_job_failed", extra={"error_code": code, "error_message": message})
    return ProviderError(HANDLER_ERRORS.get(code, TEMPORARY), detail=f"{code or 'FAILED'}: {message or raw}")
