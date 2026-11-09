"""Local, network-free provider for development.

Pastes the garment image over the torso region of the capture so the whole
pipeline (capture -> upload -> queue -> worker -> result) can be exercised
without a model. Replace with a real provider via TRYON_PROVIDER.
"""

import io

from PIL import Image

from worker.providers.base import TryOnInput, TryOnOutput, TryOnProvider

# Rough torso box as fractions of frame (x0, y0, x1, y1) per category.
_PLACEMENT = {
    "top": (0.22, 0.28, 0.78, 0.72),
    "outerwear": (0.18, 0.26, 0.82, 0.78),
    "dress": (0.22, 0.28, 0.78, 0.95),
    "bottom": (0.25, 0.55, 0.75, 0.98),
    "accessory": (0.32, 0.22, 0.68, 0.45),
}


class StubProvider(TryOnProvider):
    name = "stub"

    def run(self, inp: TryOnInput) -> TryOnOutput:
        person = Image.open(io.BytesIO(inp.person_image)).convert("RGBA")
        garment = Image.open(io.BytesIO(inp.garment_image)).convert("RGBA")

        w, h = person.size
        fx0, fy0, fx1, fy1 = _PLACEMENT.get(inp.garment_category, _PLACEMENT["top"])
        box_w, box_h = int((fx1 - fx0) * w), int((fy1 - fy0) * h)

        garment.thumbnail((box_w, box_h), Image.LANCZOS)
        gx = int(fx0 * w) + (box_w - garment.width) // 2
        gy = int(fy0 * h) + (box_h - garment.height) // 2

        # Slight transparency so the stub is obviously a stub.
        alpha = garment.getchannel("A").point(lambda a: int(a * 0.85))
        garment.putalpha(alpha)

        person.alpha_composite(garment, dest=(gx, gy))

        out = io.BytesIO()
        person.convert("RGB").save(out, format="JPEG", quality=90)
        return TryOnOutput(image=out.getvalue(), content_type="image/jpeg")
