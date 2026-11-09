"""Offline provider for development and tests.

Waits (8 seconds by default) while reporting progress, then returns the shopper's photo with each
garment pasted on top and a "MOCK TRY-ON" banner, so the whole pipeline can be exercised with no
model, no network and no cost.
"""

import io
import time
from collections.abc import Callable

from PIL import Image, ImageDraw, ImageFont

from worker.providers.base import ProgressFn, ProviderError, TryOnProvider, TryOnRequest, TryOnResult

# Where each category goes, as (x0, y0, x1, y1) fractions of the photo.
PLACEMENT = {
    "top": (0.22, 0.28, 0.78, 0.72),
    "bottom": (0.25, 0.55, 0.75, 0.98),
    "dress": (0.22, 0.28, 0.78, 0.95),
    "shoes": (0.20, 0.86, 0.80, 0.99),
    "bag": (0.60, 0.50, 0.95, 0.72),
    "accessory": (0.32, 0.20, 0.68, 0.42),
}


class MockProvider(TryOnProvider):
    name = "mock"

    def __init__(
        self,
        duration_seconds: float = 8.0,
        steps: int = 8,
        fail: bool = False,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.duration_seconds = duration_seconds
        self.steps = max(1, steps)
        self.fail = fail
        self._sleep = sleep

    def run(self, request: TryOnRequest, on_progress: ProgressFn) -> TryOnResult:
        if self.fail:
            self._sleep(min(self.duration_seconds, 1.0))
            raise ProviderError("The mock provider was set to fail (MOCK_FAIL=true).")

        for step in range(1, self.steps + 1):
            self._sleep(self.duration_seconds / self.steps)
            on_progress(round(100 * step / self.steps))

        try:
            canvas = Image.open(io.BytesIO(request.person_image)).convert("RGBA")
        except OSError as e:
            raise ProviderError("The photo could not be read.", detail=str(e)) from e

        w, h = canvas.size
        for garment in request.garments:
            try:
                art = Image.open(io.BytesIO(garment.image)).convert("RGBA")
            except OSError as e:
                raise ProviderError(
                    f"The image for {garment.name!r} could not be read.", detail=str(e)
                ) from e
            x0, y0, x1, y1 = PLACEMENT.get(garment.category, PLACEMENT["top"])
            box_w, box_h = int((x1 - x0) * w), int((y1 - y0) * h)
            art.thumbnail((box_w, box_h), Image.LANCZOS)
            alpha = art.getchannel("A").point(lambda a: int(a * 0.85))
            art.putalpha(alpha)
            canvas.alpha_composite(
                art, dest=(int(x0 * w) + (box_w - art.width) // 2, int(y0 * h) + (box_h - art.height) // 2)
            )

        self._draw_banner(canvas, [g.name for g in request.garments])
        out = io.BytesIO()
        canvas.convert("RGB").save(out, format="WEBP", quality=90)
        return TryOnResult(image=out.getvalue(), content_type="image/webp")

    @staticmethod
    def _draw_banner(canvas: Image.Image, names: list[str]) -> None:
        w, h = canvas.size
        font = ImageFont.load_default(size=max(14, w // 26))
        band_h = max(40, h // 12)
        overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)
        d.rectangle((0, h - band_h, w, h), fill=(0, 0, 0, 150))
        text = "MOCK TRY-ON  |  " + ", ".join(names)
        d.text((w // 40, h - band_h + band_h // 4), text[:70], fill=(255, 255, 255, 255), font=font)
        canvas.alpha_composite(overlay)
