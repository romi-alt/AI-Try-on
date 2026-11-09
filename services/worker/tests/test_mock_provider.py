import io

import pytest
from PIL import Image

from tests.helpers import garment_png, webp_bytes
from worker.config import Settings
from worker.providers.base import GarmentInput, ProviderError, TryOnRequest
from worker.providers.mock import MockProvider


def request(*categories) -> TryOnRequest:
    import uuid

    garments = [GarmentInput(uuid.uuid4(), f"Item {i}", c, garment_png()) for i, c in enumerate(categories)]
    return TryOnRequest(person_image=webp_bytes(), garments=garments)


def test_default_duration_is_eight_seconds():
    assert Settings(_env_file=None).mock_duration_seconds == 8.0


def test_waits_the_configured_total_time_in_equal_steps():
    slept = []
    MockProvider(duration_seconds=8, steps=8, sleep=slept.append).run(request("top"), lambda pct: None)
    assert slept == [1.0] * 8 and sum(slept) == 8


def test_reports_progress_ending_at_100():
    seen = []
    MockProvider(duration_seconds=0, steps=4, sleep=lambda s: None).run(request("top"), seen.append)
    assert seen == [25, 50, 75, 100]


def test_returns_the_person_image_with_an_overlay():
    person = webp_bytes()
    result = MockProvider(duration_seconds=0, sleep=lambda s: None).run(request("top"), lambda p: None)

    out = Image.open(io.BytesIO(result.image))
    original = Image.open(io.BytesIO(person)).convert("RGB")
    assert result.content_type == "image/webp" and out.format == "WEBP"
    assert out.size == original.size
    assert out.convert("RGB").tobytes() != original.tobytes()  # something was drawn
    assert out.convert("RGB").getpixel((5, 5)) != (0, 0, 0)  # untouched area still the photo
    # The garment (red) landed on the torso and the banner darkened the bottom strip.
    r, g, b = out.convert("RGB").getpixel((400, 480))
    assert r > g and r > b
    assert sum(out.convert("RGB").getpixel((10, 1195))) < sum(original.getpixel((10, 1195)))


def test_every_garment_in_an_outfit_is_drawn():
    one = MockProvider(duration_seconds=0, sleep=lambda s: None).run(request("top"), lambda p: None)
    two = MockProvider(duration_seconds=0, sleep=lambda s: None).run(request("top", "bottom"), lambda p: None)
    assert one.image != two.image


def test_every_category_is_supported():
    for category in ("top", "bottom", "dress", "shoes", "bag", "accessory"):
        MockProvider(duration_seconds=0, sleep=lambda s: None).run(request(category), lambda p: None)


def test_can_be_told_to_fail_with_a_readable_message():
    with pytest.raises(ProviderError) as e:
        MockProvider(duration_seconds=0, fail=True, sleep=lambda s: None).run(request("top"), lambda p: None)
    assert "MOCK_FAIL" in e.value.message


def test_unreadable_person_image_is_a_provider_error():
    bad = TryOnRequest(person_image=b"junk", garments=request("top").garments)
    with pytest.raises(ProviderError):
        MockProvider(duration_seconds=0, sleep=lambda s: None).run(bad, lambda p: None)
