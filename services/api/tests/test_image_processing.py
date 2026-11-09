"""Pure image validation/sanitising tests. No database, storage or network."""

import io

import pytest
from PIL import Image

from app.core.config import settings
from app.services.image_processing import CaptureRejected, process_capture
from tests.helpers import exif_with_gps, make_image_bytes


def reject_status(data: bytes) -> int:
    with pytest.raises(CaptureRejected) as e:
        process_capture(data)
    return e.value.status_code


def test_valid_portrait_jpeg_becomes_webp():
    out = process_capture(make_image_bytes(800, 1200, "JPEG"))

    img = Image.open(io.BytesIO(out.data))
    assert img.format == "WEBP"
    assert (out.width, out.height) == (800, 1200) == img.size


def test_valid_webp_input_is_accepted():
    assert process_capture(make_image_bytes(700, 1000, "WEBP")).height == 1000


def test_height_boundary_is_768():
    assert process_capture(make_image_bytes(600, 768)).height == 768
    assert reject_status(make_image_bytes(600, 767)) == 422


def test_landscape_and_square_are_rejected():
    assert reject_status(make_image_bytes(1200, 800)) == 422
    assert reject_status(make_image_bytes(900, 900)) == 422


def test_too_small_portrait_is_rejected_with_a_readable_message():
    with pytest.raises(CaptureRejected) as e:
        process_capture(make_image_bytes(300, 500))
    assert "500px tall" in e.value.message and "768" in e.value.message


def test_exif_and_gps_are_stripped():
    original = make_image_bytes(800, 1200, "JPEG", exif=exif_with_gps())
    assert b"SecretCameraCo" in original  # the input really carries metadata

    out = process_capture(original).data

    img = Image.open(io.BytesIO(out))
    assert len(img.getexif()) == 0
    assert b"SecretCameraCo" not in out and b"Model-X" not in out
    assert b"EXIF" not in out and b"XMP" not in out
    assert set(img.info) <= {"loop", "background"}  # nothing like exif / icc_profile / xmp


def test_icc_profile_is_dropped():
    profile = Image.core.ImageCmsProfile if False else None  # noqa: F841 - placeholder to keep intent clear
    from PIL import ImageCms

    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    original = make_image_bytes(800, 1200, "JPEG", icc_profile=icc)
    assert Image.open(io.BytesIO(original)).info.get("icc_profile")

    out = Image.open(io.BytesIO(process_capture(original).data))

    assert "icc_profile" not in out.info


def test_exif_orientation_is_applied_before_validating_and_saving():
    # Stored landscape (1200x800) with "rotate 90" flag: displays as portrait 800x1200.
    original = make_image_bytes(1200, 800, "JPEG", exif=exif_with_gps(orientation=6))

    out = process_capture(original)

    assert (out.width, out.height) == (800, 1200)
    assert Image.open(io.BytesIO(out.data)).size == (800, 1200)


def test_portrait_flagged_as_rotated_becomes_landscape_and_is_rejected():
    original = make_image_bytes(800, 1200, "JPEG", exif=exif_with_gps(orientation=6))
    assert reject_status(original) == 422


def test_pixel_content_survives_reencoding():
    out = process_capture(make_image_bytes(800, 1200, "JPEG", color=(200, 30, 30)))
    px = Image.open(io.BytesIO(out.data)).convert("RGB").getpixel((401, 603))
    assert px[0] > 150 and px[1] < 80 and px[2] < 80


@pytest.mark.parametrize("fmt", ["PNG", "GIF", "BMP", "TIFF"])
def test_other_formats_are_unsupported(fmt):
    assert reject_status(make_image_bytes(800, 1200, fmt)) == 415


def test_garbage_and_text_are_unsupported_regardless_of_claimed_type():
    assert reject_status(b"definitely not an image") == 415
    assert reject_status(b"<html><script>alert(1)</script></html>") == 415
    assert reject_status(b"\xff\xd8\xff\xe0" + b"\x00" * 10) in (415, 422)  # JPEG magic, no body


def test_truncated_file_is_rejected_as_corrupt():
    data = make_image_bytes(800, 1200, "JPEG")
    assert reject_status(data[: len(data) // 3]) == 422


def test_animated_webp_is_rejected():
    frames = [Image.new("RGB", (600, 900), c) for c in ("red", "blue")]
    buf = io.BytesIO()
    frames[0].save(buf, format="WEBP", save_all=True, append_images=frames[1:], duration=100)
    assert reject_status(buf.getvalue()) == 422


def test_pixel_ceiling_is_checked_before_decoding(monkeypatch):
    monkeypatch.setattr(settings, "capture_max_pixels", 1_000_000)
    assert reject_status(make_image_bytes(1000, 1200)) == 422  # 1.2 MP > 1 MP
    assert process_capture(make_image_bytes(800, 1000)).height == 1000  # 0.8 MP
