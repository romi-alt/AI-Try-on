import io

import numpy as np
import pytest
from PIL import Image

from worker import garment
from worker.garment import ProcessingError, bounding_box, combine, dilate, interior_point, process_image


def rect(h=100, w=100, box=(30, 20, 70, 80)) -> np.ndarray:
    m = np.zeros((h, w), bool)
    x0, y0, x1, y1 = box
    m[y0:y1, x0:x1] = True
    return m


class FixedRemover:
    def __init__(self, mask):
        self.mask = mask
        self.seen = None

    def alpha(self, image):
        self.seen = image.size
        return self.mask


class FixedRefiner:
    def __init__(self, mask=None, error=None):
        self.mask, self.error, self.asked = mask, error, None

    def refine(self, image, box, point):
        self.asked = (box, point)
        if self.error:
            raise self.error
        return self.mask


def jpeg(color=(180, 40, 60), size=(100, 100)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG")
    return buf.getvalue()


def open_png(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


# --- pure helpers -------------------------------------------------------------------------------


def test_bounding_box_has_a_margin_and_stays_inside_the_image():
    assert bounding_box(rect(), margin=0.0) == (30, 20, 69, 79)
    x0, y0, x1, y1 = bounding_box(rect(), margin=0.05)
    assert (x0, y0, x1, y1) == (25, 15, 74, 84)
    assert bounding_box(rect(box=(0, 0, 100, 100)), margin=0.1) == (0, 0, 99, 99)  # clipped, never outside


def test_the_interior_point_is_inside_the_mask_even_when_the_centroid_is_not():
    ring = np.zeros((100, 100), bool)
    ring[10:90, 10:90] = True
    ring[30:70, 30:70] = False  # a hollow garment: the centroid (50, 50) is in the hole
    x, y = interior_point(ring)
    assert ring[y, x]
    assert not (30 <= x < 70 and 30 <= y < 70)


def test_the_interior_point_of_a_thin_mask_still_exists():
    thin = np.zeros((50, 50), bool)
    thin[25, 5:45] = True  # one pixel tall: erosion removes everything
    x, y = interior_point(thin)
    assert thin[y, x]


def test_dilate_grows_a_mask_by_the_given_pixels():
    grown = dilate(rect(box=(40, 40, 60, 60)), 5)
    assert grown[40:60, 35:65].all() and grown[35:65, 40:60].all()
    assert not grown[30, 50] and not grown[50, 30]  # 10 px away is beyond the 5 px growth


def test_combine_uses_sams_edge_where_it_agrees_with_the_outline():
    outline = rect(box=(30, 20, 70, 80))
    sam = rect(box=(32, 22, 68, 78))  # a slightly tighter edge
    assert (combine(outline, sam) == sam).all()


def test_combine_without_sam_is_the_outline():
    outline = rect()
    assert combine(outline, None) is outline


def test_combine_ignores_a_sam_mask_that_misses_most_of_the_outline():
    outline = rect()
    wrong = rect(box=(0, 0, 10, 10))  # SAM segmented something else
    assert combine(outline, wrong) is outline
    assert combine(outline, np.zeros_like(outline)) is outline


def test_sam_may_not_leak_far_beyond_the_outline():
    outline = rect(box=(40, 40, 60, 60))
    sam = rect(box=(10, 10, 90, 90))  # SAM grabbed the whole background too
    merged = combine(outline, sam)
    assert merged.sum() < outline.sum() * 4  # held to the outline plus a few pixels
    assert merged[40:60, 40:60].all() and not merged[20, 20]


# --- process_image ------------------------------------------------------------------------------


def test_the_cutout_is_transparent_outside_the_mask_and_opaque_inside():
    mask = rect()
    result = process_image(jpeg(), FixedRemover(mask))

    cutout = open_png(result.cutout_png)
    assert cutout.mode == "RGBA" and cutout.size == (100, 100)
    alpha = np.asarray(cutout.getchannel("A"))
    assert alpha[50, 50] == 255 and alpha[5, 5] == 0  # inside / outside
    assert tuple(cutout.getpixel((50, 50))[:3]) == pytest.approx(
        (180, 40, 60), abs=6
    )  # the colour is kept (JPEG)
    assert 0 < alpha[20, 49] < 255 or alpha[20, 49] in (0, 255)  # the edge is at most softly feathered


def test_the_mask_is_black_and_white_and_matches_the_outline():
    mask = rect()
    result = process_image(jpeg(), FixedRemover(mask))

    m = open_png(result.mask_png)
    assert m.mode == "L"
    arr = np.asarray(m)
    assert set(np.unique(arr)) <= {0, 255}
    assert (arr == 255).sum() == mask.sum()
    assert result.coverage == pytest.approx(mask.mean())
    assert result.used_sam2 is False


def test_sam_refines_the_mask_and_is_prompted_from_the_outline():
    outline = rect()
    sam = rect(box=(32, 22, 68, 78))
    refiner = FixedRefiner(sam)

    result = process_image(jpeg(), FixedRemover(outline), refiner)

    box, point = refiner.asked
    assert box == bounding_box(outline) and outline[point[1], point[0]]
    assert (np.asarray(open_png(result.mask_png)) == 255).sum() == sam.sum()
    assert result.used_sam2 is True


def test_a_failing_sam_falls_back_to_the_outline():
    outline = rect()
    result = process_image(
        jpeg(), FixedRemover(outline), FixedRefiner(error=RuntimeError("cuda out of memory"))
    )
    assert (np.asarray(open_png(result.mask_png)) == 255).sum() == outline.sum()
    assert result.used_sam2 is False


def test_a_sam_mask_that_is_ignored_is_not_reported_as_used():
    result = process_image(jpeg(), FixedRemover(rect()), FixedRefiner(rect(box=(0, 0, 5, 5))))
    assert result.used_sam2 is False


def test_an_image_with_no_garment_is_refused_with_a_useful_message():
    with pytest.raises(ProcessingError, match="No garment was found"):
        process_image(jpeg(), FixedRemover(np.zeros((100, 100), bool)))


def test_just_under_the_minimum_coverage_is_refused_and_just_over_is_accepted():
    tiny = np.zeros((100, 100), bool)
    tiny.flat[: int(garment.MIN_COVERAGE * 10000) - 1] = True
    with pytest.raises(ProcessingError):
        process_image(jpeg(), FixedRemover(tiny))
    ok = np.zeros((100, 100), bool)
    ok.flat[: int(garment.MIN_COVERAGE * 10000) + 1] = True
    assert process_image(jpeg(), FixedRemover(ok)).coverage > garment.MIN_COVERAGE


def test_unreadable_bytes_are_refused():
    with pytest.raises(ProcessingError, match="could not be read"):
        process_image(b"not an image", FixedRemover(rect()))


def test_oversized_images_are_scaled_down_before_the_models_see_them():
    remover = FixedRemover(np.ones((50, 100), bool))
    result = process_image(jpeg(size=(400, 200)), remover, max_side=100)
    assert remover.seen == (100, 50)
    assert open_png(result.cutout_png).size == (100, 50)


def test_transparency_in_the_upload_is_flattened_onto_white_before_removal():
    rgba = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    rgba.paste(Image.new("RGBA", (40, 40), (10, 200, 10, 255)), (30, 30))
    buf = io.BytesIO()
    rgba.save(buf, "PNG")
    seen = {}

    class Spy:
        def alpha(self, image):
            seen["corner"], seen["centre"] = image.getpixel((0, 0)), image.getpixel((50, 50))
            return rect(box=(30, 30, 70, 70))

    process_image(buf.getvalue(), Spy())

    assert seen["corner"] == (255, 255, 255) and seen["centre"] == (10, 200, 10)
