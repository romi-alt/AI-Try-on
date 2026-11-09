import io
from collections import Counter

from PIL import Image, ImageChops

from app.models import ProductCategory
from scripts.seed import CATALOG, SIZES, render_image, render_mask


def test_catalog_has_20_unique_products():
    assert len(CATALOG) == 20
    assert len({s.name for s in CATALOG}) == 20


def test_every_category_is_represented():
    counts = Counter(s.category for s in CATALOG)
    assert set(counts) == set(ProductCategory)


def test_prices_are_consistent():
    for s in CATALOG:
        assert s.price_pkr > 0, s.name
        if s.sale_price_pkr is not None:
            assert 0 < s.sale_price_pkr < s.price_pkr, s.name
        assert s.stock >= 0, s.name
        assert s.colors, s.name
        assert SIZES[s.category], s.name


def test_some_products_are_on_sale_and_one_is_out_of_stock():
    assert any(s.sale_price_pkr is not None for s in CATALOG)
    assert any(s.stock == 0 for s in CATALOG)


def test_images_and_masks_render_for_every_category():
    for category in ProductCategory:
        spec = next(s for s in CATALOG if s.category == category)
        image = Image.open(io.BytesIO(render_image(category, spec.colors[0][1], spec.name)))
        mask = Image.open(io.BytesIO(render_mask(category)))
        assert image.mode == "RGBA"
        assert mask.mode == "L"
        assert image.size == mask.size
        # The mask is non-empty and every masked pixel is opaque in the image
        # (the image may have extra opaque pixels: the text label).
        assert mask.getextrema() == (0, 255)
        assert ImageChops.subtract(mask, image.getchannel("A")).getbbox() is None
