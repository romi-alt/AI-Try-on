"""Rules for "Complete your look": which categories are missing and whether two products go together.

Everything here is pure (no database), so the rules are easy to test and to change. The ranking inside the
rules
comes from the FashionCLIP embedding similarity, computed in SQL by the route.
"""

import colorsys
from collections.abc import Iterable, Sequence

from app.models.product import ProductCategory

# Categories "Complete your look" fills in, in the order they are shown. Accessories are not suggested.
LOOK_CATEGORIES: tuple[ProductCategory, ...] = (
    ProductCategory.top,
    ProductCategory.bottom,
    ProductCategory.shoes,
    ProductCategory.bag,
)

NEUTRAL_WORDS = frozenset(
    ["black", "white", "ivory", "cream", "beige", "grey", "gray", "charcoal", "navy", "denim"]
    + ["tan", "khaki", "camel", "nude", "stone", "taupe", "off-white"]
)

# A candidate's price must be within this factor of the selected items' average price either way, so a
# Rs 900 scarf is not paired with a Rs 40,000 gown.
PRICE_BAND = 4.0

# Higher is a better match. Used to rank candidates that pass the rules.
KIND_SCORE = {"neutral": 3, "tonal": 2, "analogous": 1, "complementary": 0}


def missing_categories(selected: Iterable[ProductCategory]) -> list[ProductCategory]:
    """The look categories the selection does not cover yet. A dress covers both top and bottom."""
    covered = set(selected)
    if ProductCategory.dress in covered:
        covered |= {ProductCategory.top, ProductCategory.bottom}
    return [c for c in LOOK_CATEGORIES if c not in covered]


def _hsv(hex_color: str) -> tuple[float, float, float]:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))
    hue, sat, val = colorsys.rgb_to_hsv(r, g, b)
    return hue * 360, sat, val


def is_neutral(name: str, hex_color: str) -> bool:
    """Neutrals go with everything: by name (navy, ivory, ...) or by being grey/near-white/near-black."""
    if any(word in NEUTRAL_WORDS for word in name.lower().replace("-", " ").split()):
        return True
    _, sat, val = _hsv(hex_color)
    return sat < 0.2 or val < 0.2


def colors_match(a: dict, b: dict) -> str | None:
    """How two colours relate (`neutral`, `tonal`, `analogous`, `complementary`), or None when they clash."""
    if is_neutral(a["name"], a["hex"]) or is_neutral(b["name"], b["hex"]):
        return "neutral"
    gap = abs(_hsv(a["hex"])[0] - _hsv(b["hex"])[0])
    gap = min(gap, 360 - gap)
    if gap <= 30:
        return "tonal"
    if gap <= 60:
        return "analogous"
    if gap >= 150:
        return "complementary"
    return None  # the awkward middle of the wheel (about 60 to 150 degrees apart)


def products_match(candidate_colors: Sequence[dict], selected_colors: Sequence[dict]) -> str | None:
    """Best relation between any colour of the candidate and any colour of one selected product.

    A product with no colour information cannot clash, so it counts as neutral.
    """
    if not candidate_colors or not selected_colors:
        return "neutral"
    kinds = [k for c in candidate_colors for s in selected_colors if (k := colors_match(c, s))]
    return max(kinds, key=KIND_SCORE.__getitem__) if kinds else None


def look_match(
    candidate_colors: Sequence[dict], selected: Sequence[Sequence[dict]]
) -> tuple[str, int] | None:
    """Whether the candidate goes with *every* selected product, and how well (the weakest pairing counts)."""
    kinds = []
    for colors in selected:
        kind = products_match(candidate_colors, colors)
        if kind is None:
            return None
        kinds.append(kind)
    if not kinds:
        return "neutral", KIND_SCORE["neutral"]
    weakest = min(kinds, key=KIND_SCORE.__getitem__)
    return weakest, KIND_SCORE[weakest]


def price_ok(candidate_price: int, selected_prices: Sequence[int]) -> bool:
    if not selected_prices:
        return True
    mean = sum(selected_prices) / len(selected_prices)
    if mean <= 0:
        return True
    return mean / PRICE_BAND <= candidate_price <= mean * PRICE_BAND


REASONS = {
    "neutral": "A neutral that goes with everything you chose",
    "tonal": "Matches the tone of your look",
    "analogous": "Sits next to your colours on the colour wheel",
    "complementary": "A complementary colour to your look",
}
