"""Small image helpers shared by providers that send pictures over HTTP."""

import io

from PIL import Image, UnidentifiedImageError

from worker.providers.base import ProviderError


def to_jpeg(data: bytes, *, max_side: int | None = None, quality: int = 92) -> bytes:
    """Flatten to a white-background JPEG, optionally scaled so the longest side is at most `max_side`.

    Flat-lay garment PNGs are transparent; a model that is not given an alpha channel needs them on white.
    """
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError) as e:
        raise ProviderError("An image could not be read.", detail=str(e)) from e
    rgba = img.convert("RGBA")
    flat = Image.new("RGB", rgba.size, (255, 255, 255))
    flat.paste(rgba, mask=rgba.getchannel("A"))
    if max_side and max(flat.size) > max_side:
        scale = max_side / max(flat.size)
        flat = flat.resize((round(flat.width * scale), round(flat.height * scale)), Image.LANCZOS)
    out = io.BytesIO()
    flat.save(out, format="JPEG", quality=quality)
    return out.getvalue()


def sniff_content_type(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"
