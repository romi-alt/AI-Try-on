"""Runs a try-on request with CatVTON. Everything that is not the GPU lives here, so it can be tested.

The heavy objects are passed in (see `loader.py`, which builds them once at worker start-up):

- `automasker(person, cloth_type)` -> `{"mask": PIL.Image}`: CatVTON's AutoMasker, which runs DensePose and
  the SCHP human-parsing model on the person photo and returns the region to repaint. It runs on every job,
  because every job has a different person.
- `pipeline(image=..., condition_image=..., mask=..., num_inference_steps=..., guidance_scale=...,
  height=..., width=..., generator=...)` -> `[PIL.Image]`: the CatVTON diffusion pipeline.

One garment is dressed per pass (upper body, lower body or whole body), so an outfit is built by feeding each
result back in as the next pass's person. Progress comes from the diffusion loop: the pipeline's noise
scheduler is stepped once per denoising step, so counting its `step` calls gives exact progress across all
passes.
"""

import base64
import binascii
import io
import json
import logging
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from PIL import Image, ImageOps, UnidentifiedImageError

logger = logging.getLogger("catvton.runner")

WIDTH, HEIGHT = 768, 1024
CLOTH_TYPES = {"top": "upper", "bottom": "lower", "dress": "overall"}
MAX_GARMENTS = 4
MAX_STEPS = 50
# A person mask covering less of the frame than this means the parsing model did not find a body to dress.
MIN_MASK_FRACTION = 0.01


class RunnerError(Exception):
    """A failure the client can show the shopper. `code` is one of the provider's HANDLER_ERRORS keys."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

    def as_error_string(self) -> str:
        return json.dumps({"code": self.code, "message": self.message})


ProgressFn = Callable[[int], None]


@contextmanager
def count_diffusion_steps(pipeline, on_step: Callable[[], None]) -> Iterator[None]:
    """Call `on_step()` each time the pipeline's scheduler takes a denoising step, within the block."""
    scheduler = next(
        (getattr(pipeline, name) for name in ("noise_scheduler", "scheduler") if hasattr(pipeline, name)),
        None,
    )
    if scheduler is None or not hasattr(scheduler, "step"):
        raise RuntimeError(
            "The CatVTON pipeline has no scheduler to count steps on; check the pinned CatVTON version"
        )
    original = scheduler.step

    def counted(*args, **kwargs):
        result = original(*args, **kwargs)
        on_step()
        return result

    scheduler.step = counted
    try:
        yield
    finally:
        scheduler.step = original


def decode_image(b64: str, what: str) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(base64.b64decode(b64, validate=True)))
        img.load()
    except (
        binascii.Error,
        ValueError,
        UnidentifiedImageError,
        OSError,
        TypeError,
    ) as e:
        raise RunnerError("bad_image", f"The {what} could not be read: {e!r}") from e
    return ImageOps.exif_transpose(img).convert("RGB")


def fit_person(img: Image.Image) -> Image.Image:
    """Cover-crop to 3:4 and resize to 768x1024 (the kiosk sends 3:4, so this normally just resizes)."""
    return ImageOps.fit(img, (WIDTH, HEIGHT), Image.LANCZOS, centering=(0.5, 0.5))


def fit_garment(img: Image.Image) -> Image.Image:
    """Pad onto white to 3:4 without cropping any of the garment, then resize to 768x1024."""
    scale = min(WIDTH / img.width, HEIGHT / img.height)
    resized = img.resize(
        (max(1, round(img.width * scale)), max(1, round(img.height * scale))),
        Image.LANCZOS,
    )
    canvas = Image.new("RGB", (WIDTH, HEIGHT), (255, 255, 255))
    canvas.paste(resized, ((WIDTH - resized.width) // 2, (HEIGHT - resized.height) // 2))
    return canvas


def mask_fraction(mask: Image.Image) -> float:
    gray = mask.convert("L")
    hist = gray.histogram()
    return sum(hist[128:]) / max(1, gray.width * gray.height)


class CatVTONRunner:
    def __init__(
        self,
        pipeline,
        automasker,
        *,
        make_generator: Callable[[int], object] | None = None,
    ):
        self.pipeline = pipeline
        self.automasker = automasker
        self._make_generator = make_generator or _torch_generator

    def run(self, payload: dict, on_progress: ProgressFn) -> dict:
        """Returns `{"image": base64 JPEG, "content_type", "width", "height", "timings"}` or raises."""
        garments, steps, guidance, seed = self._validate(payload)
        person = fit_person(decode_image(payload.get("person_image", ""), "photo"))
        cloths = [
            fit_garment(decode_image(g.get("image", ""), f"garment {i + 1}")) for i, g in enumerate(garments)
        ]

        total_steps = steps * len(garments)
        done = 0
        last_pct = -1

        def on_step() -> None:
            nonlocal done, last_pct
            done += 1
            pct = min(99, round(100 * done / total_steps))
            if pct != last_pct:
                last_pct = pct
                on_progress(pct)

        timings = {"mask_s": 0.0, "diffusion_s": 0.0}
        started = time.monotonic()
        on_progress(0)
        try:
            with count_diffusion_steps(self.pipeline, on_step):
                for garment, cloth in zip(garments, cloths, strict=True):
                    t = time.monotonic()
                    mask = self.automasker(person, CLOTH_TYPES[garment["category"]])["mask"]
                    timings["mask_s"] += time.monotonic() - t
                    if mask_fraction(mask) < MIN_MASK_FRACTION:
                        raise RunnerError("no_person", "No body was found to dress in the photo")
                    t = time.monotonic()
                    out = self.pipeline(
                        image=person,
                        condition_image=cloth,
                        mask=mask,
                        num_inference_steps=steps,
                        guidance_scale=guidance,
                        height=HEIGHT,
                        width=WIDTH,
                        generator=self._make_generator(seed),
                    )
                    timings["diffusion_s"] += time.monotonic() - t
                    person = out[0].convert("RGB")
                    if person.size != (WIDTH, HEIGHT):
                        person = person.resize((WIDTH, HEIGHT), Image.LANCZOS)
        except RunnerError:
            raise
        except Exception as e:
            if (
                type(e).__name__ == "OutOfMemoryError"
            ):  # torch.cuda.OutOfMemoryError, without importing torch here
                raise RunnerError("out_of_memory", "The GPU ran out of memory") from e
            raise

        buf = io.BytesIO()
        person.save(buf, format="JPEG", quality=92)
        timings["total_s"] = time.monotonic() - started
        logger.info("catvton_done", extra={k: round(v, 2) for k, v in timings.items()})
        on_progress(100)
        return {
            "image": base64.b64encode(buf.getvalue()).decode(),
            "content_type": "image/jpeg",
            "width": WIDTH,
            "height": HEIGHT,
            "timings": {k: round(v, 3) for k, v in timings.items()},
        }

    @staticmethod
    def _validate(payload: dict) -> tuple[list[dict], int, float, int]:
        if not isinstance(payload, dict) or not payload.get("person_image"):
            raise RunnerError("bad_image", "person_image is required")
        garments = payload.get("garments")
        if not isinstance(garments, list) or not garments or len(garments) > MAX_GARMENTS:
            raise RunnerError("bad_image", f"garments must be a list of 1 to {MAX_GARMENTS} items")
        for g in garments:
            if not isinstance(g, dict) or g.get("category") not in CLOTH_TYPES:
                raise RunnerError(
                    "unsupported_category",
                    f"category must be one of {sorted(CLOTH_TYPES)}",
                )
        try:
            steps = int(payload.get("steps", 30))
            guidance = float(payload.get("guidance_scale", 2.5))
            seed = int(payload.get("seed", 555))
        except (TypeError, ValueError) as e:
            raise RunnerError("bad_image", "steps, guidance_scale and seed must be numbers") from e
        if not 1 <= steps <= MAX_STEPS:
            raise RunnerError("bad_image", f"steps must be between 1 and {MAX_STEPS}")
        return garments, steps, guidance, seed


def _torch_generator(seed: int):
    import torch  # only on the GPU worker

    return torch.Generator(device="cuda").manual_seed(seed)
