"""FASHN hosted virtual try-on (https://docs.fashn.ai).

Flow per garment: POST {base}/run -> {"id"}, then poll GET {base}/status/{id} until `completed`
(statuses: starting, in_queue, processing, completed, failed), then download `output[0]`.
FASHN dresses one garment per call, so an outfit is built by feeding each result back in as the
next call's person image. Only tops, bottoms and dresses are supported by the model.

Every failure is turned into a ProviderError whose message is fit to show a shopper; the technical
detail (FASHN error name/message, HTTP status) goes to the logs.
"""

import base64
import io
import logging
import time
from collections.abc import Callable

import httpx
from PIL import Image, UnidentifiedImageError

from worker.config import settings
from worker.providers.base import (
    GarmentInput,
    ProgressFn,
    ProviderError,
    TryOnProvider,
    TryOnRequest,
    TryOnResult,
)

logger = logging.getLogger("worker.fashn")

CATEGORY_MAP = {"top": "tops", "bottom": "bottoms", "dress": "one-pieces"}
IN_PROGRESS = {"starting", "in_queue", "processing"}
# Rough server-side time per mode, only used to animate the progress bar while FASHN works.
EXPECTED_SECONDS = {"performance": 5.0, "balanced": 8.0, "quality": 15.0}
RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_RUN_ATTEMPTS = 3
MAX_POLL_ERRORS = 3

TEMPORARY = "The try-on service had a temporary problem. Please try again."
BUSY = "The try-on service is very busy right now. Please try again in a moment."
UNREACHABLE = "Couldn't reach the try-on service. Please try again."
TOO_SLOW = "The try-on service took too long. Please try again."
MISCONFIGURED = "The try-on service isn't set up correctly. Please ask staff for help."

# FASHN runtime error name -> what the shopper sees.
RUNTIME_ERRORS = {
    "PoseError": "We couldn't see your full body clearly. Stand back so you're fully in frame and try again.",
    "ContentModerationError": "This photo or garment was blocked by the content filter. Try another photo.",
    "ImageLoadError": "The try-on service couldn't read the photo or the garment image.",
    "InputValidationError": "The try-on service rejected the photo or the garment image.",
    "ThirdPartyError": TEMPORARY,
    "UnavailableError": TEMPORARY,
    "PipelineError": TEMPORARY,
}
# FASHN API-level error name -> what the shopper sees.
API_ERRORS = {
    "UnauthorizedAccess": MISCONFIGURED,
    "OutOfCredits": "The try-on service is out of credits. Please ask staff for help.",
    "RateLimitExceeded": BUSY,
    "ConcurrencyLimitExceeded": BUSY,
    "BadRequest": "The try-on service rejected the request.",
}


class FashnProvider(TryOnProvider):
    name = "fashn"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        model_name: str | None = None,
        mode: str | None = None,
        poll_interval: float | None = None,
        timeout: float | None = None,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.api_key = api_key if api_key is not None else settings.fashn_api_key
        if not self.api_key:
            raise RuntimeError("TRYON_PROVIDER=fashn requires FASHN_API_KEY to be set")
        self.base_url = (base_url or settings.fashn_base_url).rstrip("/")
        self.model_name = model_name or settings.fashn_model_name
        self.mode = mode or settings.fashn_mode
        self.poll_interval = settings.fashn_poll_interval_seconds if poll_interval is None else poll_interval
        self.timeout = settings.fashn_timeout_seconds if timeout is None else timeout
        self._http = client or httpx.Client(timeout=30)
        self._sleep = sleep
        self._clock = clock

    # --- public ----------------------------------------------------------------------------

    def run(self, request: TryOnRequest, on_progress: ProgressFn) -> TryOnResult:
        unsupported = [g.name for g in request.garments if g.category not in CATEGORY_MAP]
        if unsupported:
            raise ProviderError(
                "Virtual try-on works for tops, bottoms and dresses only. "
                f"Please remove: {', '.join(unsupported)}."
            )

        current = _to_jpeg(request.person_image)
        total = len(request.garments)
        for index, garment in enumerate(request.garments):
            start, span = 100 * index / total, 100 / total
            on_progress(round(start))
            current = self._try_on_one(
                current, garment, lambda fraction, s=start, w=span: on_progress(round(s + w * fraction))
            )
        on_progress(100)
        return TryOnResult(image=current, content_type=_sniff_content_type(current))

    # --- one garment -----------------------------------------------------------------------

    def _try_on_one(self, person: bytes, garment: GarmentInput, report: Callable[[float], None]) -> bytes:
        payload = {
            "model_name": self.model_name,
            "inputs": {
                "model_image": _data_uri(person, "image/jpeg"),
                "garment_image": _data_uri(_to_jpeg(garment.image), "image/jpeg"),
                "category": CATEGORY_MAP[garment.category],
                "mode": self.mode,
                "garment_photo_type": "auto",
                "num_samples": 1,
                "output_format": "jpeg",
            },
        }
        prediction_id = self._submit(payload)
        report(0.05)
        output_url = self._wait(prediction_id, report)
        return self._download(output_url)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _submit(self, payload: dict) -> str:
        for attempt in range(1, MAX_RUN_ATTEMPTS + 1):
            try:
                resp = self._http.post(f"{self.base_url}/run", json=payload, headers=self._headers())
            except httpx.TimeoutException as e:
                raise ProviderError(TOO_SLOW, detail=f"POST /run timed out: {e}") from e
            except httpx.TransportError as e:
                raise ProviderError(UNREACHABLE, detail=f"POST /run failed: {e!r}") from e

            if resp.status_code == 200:
                body = resp.json()
                if body.get("error") or not body.get("id"):
                    raise ProviderError(
                        TEMPORARY, detail=f"unexpected /run response with keys {sorted(body)}"
                    )
                return body["id"]

            name, message = _api_error(resp)
            logger.warning(
                "fashn_run_rejected",
                extra={
                    "http_status": resp.status_code,
                    "error_name": name,
                    "error_message": message,
                    "attempt": attempt,
                },
            )
            retryable = resp.status_code in RETRY_STATUSES and name != "OutOfCredits"
            if retryable and attempt < MAX_RUN_ATTEMPTS:
                self._sleep(_retry_delay(resp, attempt))
                continue
            raise ProviderError(
                API_ERRORS.get(name, BUSY if resp.status_code == 429 else TEMPORARY),
                detail=f"{resp.status_code} {name}: {message}",
            )
        raise AssertionError("unreachable")  # pragma: no cover

    def _wait(self, prediction_id: str, report: Callable[[float], None]) -> str:
        started = self._clock()
        expected = EXPECTED_SECONDS.get(self.mode, 8.0)
        errors = 0
        while True:
            elapsed = self._clock() - started
            if elapsed > self.timeout:
                raise ProviderError(
                    TOO_SLOW, detail=f"prediction {prediction_id} not done after {elapsed:.0f}s"
                )
            try:
                resp = self._http.get(f"{self.base_url}/status/{prediction_id}", headers=self._headers())
                resp.raise_for_status()
                body = resp.json()
                errors = 0
            except (httpx.TransportError, httpx.HTTPStatusError) as e:
                errors += 1
                if errors >= MAX_POLL_ERRORS:
                    raise ProviderError(UNREACHABLE, detail=f"status polling failed {errors}x: {e!r}") from e
                self._sleep(self.poll_interval)
                continue

            status = body.get("status")
            if status == "completed":
                output = body.get("output") or []
                if not output:
                    raise ProviderError(
                        TEMPORARY, detail=f"completed without output; response keys {sorted(body)}"
                    )
                report(1.0)
                return output[0]
            if status == "failed":
                err = body.get("error") or {}
                name, message = err.get("name", "UnknownError"), err.get("message", "")
                logger.warning(
                    "fashn_prediction_failed",
                    extra={"prediction_id": prediction_id, "error_name": name, "error_message": message},
                )
                raise ProviderError(RUNTIME_ERRORS.get(name, TEMPORARY), detail=f"{name}: {message}")
            if status not in IN_PROGRESS:
                raise ProviderError(TEMPORARY, detail=f"unknown status {status!r}")

            report(0.1 if status in ("starting", "in_queue") else min(0.9, 0.2 + 0.7 * elapsed / expected))
            self._sleep(self.poll_interval)

    def _download(self, url: str) -> bytes:
        try:
            # Plain GET: the result CDN needs no credentials, so the API key is not sent to it.
            resp = self._http.get(url)
            resp.raise_for_status()
        except httpx.TimeoutException as e:
            raise ProviderError(TOO_SLOW, detail=f"download timed out: {e}") from e
        except (httpx.TransportError, httpx.HTTPStatusError) as e:
            raise ProviderError(TEMPORARY, detail=f"could not download result: {e!r}") from e
        return resp.content


# --- helpers -------------------------------------------------------------------------------


def _data_uri(data: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def _to_jpeg(data: bytes) -> bytes:
    """Flatten to a white-background JPEG: widely accepted, and flat-lay PNGs lose transparency."""
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError) as e:
        raise ProviderError("An image could not be read.", detail=str(e)) from e
    rgba = img.convert("RGBA")
    flat = Image.new("RGB", rgba.size, (255, 255, 255))
    flat.paste(rgba, mask=rgba.getchannel("A"))
    out = io.BytesIO()
    flat.save(out, format="JPEG", quality=92)
    return out.getvalue()


def _sniff_content_type(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def _api_error(resp: httpx.Response) -> tuple[str, str]:
    try:
        body = resp.json()
        return str(body.get("error", f"HTTP{resp.status_code}")), str(body.get("message", ""))
    except ValueError:
        return f"HTTP{resp.status_code}", resp.text[:200]


def _retry_delay(resp: httpx.Response, attempt: int) -> float:
    try:
        return min(float(resp.headers["retry-after"]), 30.0)
    except (KeyError, ValueError):
        return float(2**attempt)  # 2s, 4s
