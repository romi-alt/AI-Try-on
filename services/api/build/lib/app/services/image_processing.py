"""Validation and sanitising of webcam captures.

The input is untrusted: its format is decided by sniffing the bytes (never the client's
Content-Type), its size is checked from the header before any pixel decoding, and the stored
output is re-encoded from raw pixels so no metadata (EXIF, GPS, ICC, XMP) can survive.
"""

import io
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import settings

ALLOWED_FORMATS = {"JPEG", "WEBP"}
OUTPUT_QUALITY = 90


class CaptureRejected(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@dataclass(frozen=True)
class ProcessedCapture:
    data: bytes
    width: int
    height: int


def process_capture(data: bytes) -> ProcessedCapture:
    try:
        img = Image.open(io.BytesIO(data))
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as e:
        raise CaptureRejected(415, "Unsupported or unreadable image. Send a JPEG or WebP.") from e

    if img.format not in ALLOWED_FORMATS:
        raise CaptureRejected(415, f"Unsupported image format {img.format}. Send a JPEG or WebP.")
    if getattr(img, "is_animated", False):
        raise CaptureRejected(422, "Animated images are not supported.")

    # Header-only check: refuse huge images before spending memory/CPU decoding them.
    if img.width * img.height > settings.capture_max_pixels:
        raise CaptureRejected(422, "Image resolution is too large.")

    try:
        img.load()
        # Apply the camera's orientation first: a phone photo stored sideways with an EXIF
        # rotation flag is judged (and saved) the way it will actually be displayed.
        img = ImageOps.exif_transpose(img)
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError) as e:
        raise CaptureRejected(422, "The image file is corrupt or truncated.") from e

    width, height = img.size
    if height < settings.capture_min_height:
        raise CaptureRejected(
            422, f"Image is too small: {height}px tall, at least {settings.capture_min_height}px required."
        )
    if height <= width:
        raise CaptureRejected(422, f"Image must be portrait (taller than wide); got {width}x{height}.")

    # Rebuild from pixels only: a fresh image has no EXIF/ICC/XMP to carry over.
    clean = Image.new("RGB", (width, height))
    clean.paste(img.convert("RGB"))
    out = io.BytesIO()
    clean.save(out, format="WEBP", quality=OUTPUT_QUALITY, method=4)
    return ProcessedCapture(data=out.getvalue(), width=width, height=height)
