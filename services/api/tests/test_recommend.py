import uuid

import pytest

from app.models import ProductCategory as C
from app.services import recommend as rules
from tests.helpers import make_product

RED = {"name": "Red", "hex": "#d62828"}
TEAL = {"name": "Teal", "hex": "#2a9d8f"}  # about 175 degrees from red: complementary
ORANGE = {"name": "Orange", "hex": "#f77f00"}  # about 30 degrees: tonal or analogous
LIME = {"name": "Lime", "hex": "#9acd32"}  # about 80 degrees: the awkward middle
BLUE = {"name": "Blue", "hex": "#1d4ed8"}
BLACK = {"name": "Black", "hex": "#000000"}
IVORY = {"name": "Ivory", "hex": "#efe6d2"}


# --- rules (no database) ------------------------------------------------------------------------


def test_missing_categories_covers_top_bottom_shoes_and_bag():
    assert rules.missing_categories([C.top]) == [C.bottom, C.shoes, C.bag]
    assert rules.missing_categories([C.top, C.shoes]) == [C.bottom, C.bag]
    assert rules.missing_categories([C.top, C.bottom, C.shoes, C.bag]) == []
    assert rules.missing_categories([C.accessory]) == [
        C.top,
        C.bottom,
        C.shoes,
        C.bag,
    ]  # accessories fill nothing
    assert rules.missing_categories([]) == [C.top, C.bottom, C.shoes, C.bag]


def test_a_dress_covers_top_and_bottom():
    assert rules.missing_categories([C.dress]) == [C.shoes, C.bag]
    assert rules.missing_categories([C.dress, C.top]) == [C.shoes, C.bag]


@pytest.mark.parametrize(
    ("color", "neutral"),
    [
        (BLACK, True),
        (IVORY, True),
        ({"name": "Navy", "hex": "#1f2a44"}, True),  # by name
        ({"name": "Slate", "hex": "#808080"}, True),  # grey by number
        ({"name": "Midnight", "hex": "#0a0a14"}, True),  # near black by number
        (RED, False),
        (TEAL, False),
    ],
)
def test_neutrals(color, neutral):
    assert rules.is_neutral(color["name"], color["hex"]) is neutral


def test_colour_relations():
    assert rules.colors_match(RED, BLACK) == "neutral"
    assert rules.colors_match(BLACK, RED) == "neutral"  # symmetric
    assert rules.colors_match(RED, TEAL) == "complementary"
    assert rules.colors_match(RED, {"name": "Crimson", "hex": "#c1121f"}) == "tonal"
    assert rules.colors_match(RED, ORANGE) in ("tonal", "analogous")
    assert rules.colors_match(RED, LIME) is None
    assert rules.colors_match(RED, BLUE) is None  # 120 degrees apart: the awkward middle


def test_a_product_matches_through_its_best_colour_pair():
    assert rules.products_match([LIME, BLACK], [RED]) == "neutral"  # one of its colours is a neutral
    assert rules.products_match([LIME], [RED]) is None
    assert rules.products_match([], [RED]) == "neutral"  # no colour information cannot clash
    assert rules.products_match([RED], []) == "neutral"


def test_a_look_needs_every_selected_item_to_agree_and_the_weakest_pairing_counts():
    assert rules.look_match([TEAL], [[RED], [LIME]]) is None  # clashes with the second
    kind, score = rules.look_match([TEAL], [[BLACK], [RED]])
    assert kind == "complementary" and score == rules.KIND_SCORE["complementary"]
    assert rules.look_match([BLACK], [[RED], [BLUE]]) == ("neutral", rules.KIND_SCORE["neutral"])
    assert rules.look_match([TEAL], []) == ("neutral", rules.KIND_SCORE["neutral"])


def test_price_band():
    assert rules.price_ok(1000, [1000])
    assert rules.price_ok(4000, [1000]) and not rules.price_ok(4001, [1000])
    assert rules.price_ok(250, [1000]) and not rules.price_ok(249, [1000])
    assert rules.price_ok(1500, [500, 1500])  # against the average of the selection
    assert rules.price_ok(5, [])
    assert rules.price_ok(5, [0])


# --- route (real pgvector) ----------------------------------------------------------------------


def vec(*head: float) -> list[float]:
    return list(head) + [0.0] * (512 - len(head))


def ids(*products) -> str:
    return ",".join(str(p.id) for p in products)


def names(items) -> list[str]:
    return [i["name"] for i in items]


async def test_more_styles_are_the_nearest_in_the_same_category(api, adb):
    anchor = await make_product(adb, name="Anchor", category=C.top, embedding=vec(1, 0))
    await make_product(adb, name="Near", category=C.top, embedding=vec(0.9, 0.1))
    await make_product(adb, name="Mid", category=C.top, embedding=vec(0.5, 0.5))
    await make_product(adb, name="Far", category=C.top, embedding=vec(0, 1))
    await make_product(
        adb, name="OtherCategory", category=C.bottom, embedding=vec(1, 0)
    )  # closest but wrong category
    await make_product(adb, name="SoldOut", category=C.top, embedding=vec(0.99, 0.01), stock=0)

    r = await api.get("/recommend", params={"product_ids": ids(anchor)})

    assert r.status_code == 200
    got = [
        i
        for i in r.json()["more_styles"]
        if i["name"] in {"Near", "Mid", "Far", "OtherCategory", "SoldOut", "Anchor"}
    ]
    assert names(got) == [
        "Near",
        "Mid",
        "Far",
    ]  # ordered by distance; no selected, wrong-category or sold-out items
    assert all(isinstance(i["distance"], float) for i in got)
    assert got[0]["distance"] < got[1]["distance"] < got[2]["distance"]
    assert all(i["current_price_pkr"] is not None for i in got)  # full product payload for the kiosk


async def test_more_styles_keeps_the_eight_nearest_out_of_many(api, adb):
    anchor = await make_product(adb, name="Hub", category=C.top, embedding=vec(1, 0))
    for n in range(12):  # n=0 is the nearest, n=11 the farthest
        await make_product(adb, name=f"Spoke{n:02d}", category=C.top, embedding=vec(1 - n * 0.05, n * 0.05))

    r = await api.get("/recommend", params={"product_ids": ids(anchor)})

    got = [i["name"] for i in r.json()["more_styles"] if i["name"].startswith("Spoke")]
    assert got == [f"Spoke{n:02d}" for n in range(8)]


async def test_more_styles_merges_several_selected_items_by_their_closest_distance(api, adb):
    a = await make_product(adb, name="A", category=C.top, embedding=vec(1, 0))
    b = await make_product(adb, name="B", category=C.shoes, embedding=vec(0, 1))
    top_near_a = await make_product(adb, name="TopNearA", category=C.top, embedding=vec(0.95, 0.05))
    shoe_near_b = await make_product(adb, name="ShoeNearB", category=C.shoes, embedding=vec(0.05, 0.95))

    r = await api.get("/recommend", params={"product_ids": ids(a, b)})

    got = {i["name"] for i in r.json()["more_styles"]}
    assert {"TopNearA", "ShoeNearB"} <= got
    assert top_near_a.name not in {"A", "B"} and shoe_near_b.name not in {"A", "B"}
    assert len([i for i in r.json()["more_styles"] if i["name"] == "TopNearA"]) == 1  # not repeated


async def test_without_embeddings_more_styles_falls_back_to_newest_in_category(api, adb):
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    anchor = await make_product(adb, name="NoVec", category=C.bag, embedding=None)
    new = await make_product(adb, name="NewBag", category=C.bag, created_at=now + timedelta(days=1))
    old = await make_product(adb, name="OldBag", category=C.bag, created_at=now - timedelta(days=9))

    r = await api.get("/recommend", params={"product_ids": ids(anchor)})

    got = [i for i in r.json()["more_styles"] if i["name"] in {"NewBag", "OldBag"}]
    assert names(got) == ["NewBag", "OldBag"] and all(i["distance"] is None for i in got)
    assert new.id and old.id


async def test_complete_your_look_fills_only_the_missing_categories(api, adb):
    top = await make_product(adb, name="MyTop", category=C.top, colors=[BLACK], embedding=vec(1, 0))
    for cat in (C.top, C.bottom, C.shoes, C.bag, C.accessory):
        await make_product(
            adb, name=f"Cand-{cat.value}", category=cat, colors=[BLACK], embedding=vec(0.9, 0.1)
        )

    r = await api.get("/recommend", params={"product_ids": ids(top)})

    look = {
        s["category"]: s for s in r.json()["complete_your_look"] if s["product"]["name"].startswith("Cand-")
    }
    assert set(look) == {"bottom", "shoes", "bag"}  # not top (covered) and not accessory (never suggested)
    assert [s["category"] for s in r.json()["complete_your_look"]] == [
        "bottom",
        "shoes",
        "bag",
    ]  # fixed order
    assert look["bottom"]["reason"] == rules.REASONS["neutral"]
    assert 0.9 < look["bottom"]["similarity"] <= 1.0


async def test_a_dress_needs_only_shoes_and_a_bag(api, adb):
    dress = await make_product(adb, name="MyDress", category=C.dress, colors=[BLACK])
    for cat in (C.top, C.bottom, C.shoes, C.bag):
        await make_product(adb, name=f"Cand-{cat.value}", category=cat, colors=[BLACK])

    r = await api.get("/recommend", params={"product_ids": ids(dress)})

    assert [s["category"] for s in r.json()["complete_your_look"]] == ["shoes", "bag"]


async def test_the_closest_compatible_item_wins_and_clashing_ones_are_skipped(api, adb):
    top = await make_product(adb, name="RedTop", category=C.top, colors=[RED], embedding=vec(1, 0))
    clash = await make_product(
        adb, name="ClashSkirt", category=C.bottom, colors=[LIME], embedding=vec(0.99, 0.01)
    )
    good_far = await make_product(
        adb, name="TealSkirt", category=C.bottom, colors=[TEAL], embedding=vec(0.6, 0.4)
    )
    good_near = await make_product(
        adb, name="BlackSkirt", category=C.bottom, colors=[BLACK], embedding=vec(0.9, 0.1)
    )

    r = await api.get("/recommend", params={"product_ids": ids(top)})

    bottom = next(s for s in r.json()["complete_your_look"] if s["category"] == "bottom")
    assert bottom["product"]["name"] == "BlackSkirt"  # the closest one that does not clash
    assert clash.id and good_far.id and good_near.id


async def test_complementary_colours_are_allowed_but_explained(api, adb):
    top = await make_product(adb, name="RedTop2", category=C.top, colors=[RED], embedding=vec(1, 0))
    await make_product(adb, name="TealBag", category=C.bag, colors=[TEAL], embedding=vec(0.8, 0.2))

    r = await api.get("/recommend", params={"product_ids": ids(top)})

    bag = next(s for s in r.json()["complete_your_look"] if s["category"] == "bag")
    assert bag["product"]["name"] == "TealBag" and bag["reason"] == rules.REASONS["complementary"]


async def test_a_candidate_must_go_with_every_selected_item(api, adb):
    red = await make_product(adb, name="RedTop3", category=C.top, colors=[RED])
    lime_shoes = await make_product(adb, name="LimeShoes", category=C.shoes, colors=[LIME])
    await make_product(
        adb, name="TealBag3", category=C.bag, colors=[TEAL]
    )  # goes with red, clashes with lime

    r = await api.get("/recommend", params={"product_ids": ids(red, lime_shoes)})

    assert "bag" not in [
        s["category"] for s in r.json()["complete_your_look"] if s["product"]["name"] == "TealBag3"
    ]


async def test_out_of_stock_and_wildly_priced_items_are_not_suggested(api, adb):
    top = await make_product(
        adb, name="PricedTop", category=C.top, colors=[BLACK], price_pkr=2000, sale_price_pkr=None
    )
    await make_product(adb, name="GoneSkirt", category=C.bottom, colors=[BLACK], stock=0, price_pkr=2000)
    await make_product(adb, name="GownSkirt", category=C.bottom, colors=[BLACK], price_pkr=90000)  # over 4x
    await make_product(
        adb, name="PennySkirt", category=C.bottom, colors=[BLACK], price_pkr=100
    )  # under a quarter
    ok = await make_product(adb, name="FairSkirt", category=C.bottom, colors=[BLACK], price_pkr=3000)

    r = await api.get("/recommend", params={"product_ids": ids(top)})

    bottoms = [s["product"]["name"] for s in r.json()["complete_your_look"] if s["category"] == "bottom"]
    assert bottoms == ["FairSkirt"] and ok.id


async def test_the_sale_price_is_what_counts_for_the_price_band(api, adb):
    top = await make_product(
        adb, name="SaleTop", category=C.top, colors=[BLACK], price_pkr=10000, sale_price_pkr=1000
    )
    await make_product(
        adb, name="CheapSkirt", category=C.bottom, colors=[BLACK], price_pkr=800
    )  # near 1000, far from 10000

    r = await api.get("/recommend", params={"product_ids": ids(top)})

    assert "CheapSkirt" in [s["product"]["name"] for s in r.json()["complete_your_look"]]


async def test_a_category_with_no_valid_candidate_is_left_out(api, adb):
    top = await make_product(adb, name="LoneTop", category=C.top, colors=[RED])
    await make_product(adb, name="LimeBag", category=C.bag, colors=[LIME])  # the only bag, and it clashes

    r = await api.get("/recommend", params={"product_ids": ids(top)})

    assert "LimeBag" not in [s["product"]["name"] for s in r.json()["complete_your_look"]]


async def test_selected_items_are_never_suggested_back(api, adb):
    top = await make_product(adb, name="SelTop", category=C.top, colors=[BLACK], embedding=vec(1, 0))
    shoes = await make_product(adb, name="SelShoes", category=C.shoes, colors=[BLACK], embedding=vec(1, 0))

    r = await api.get("/recommend", params={"product_ids": ids(top, shoes)})

    everything = r.json()["more_styles"] + [s["product"] for s in r.json()["complete_your_look"]]
    assert not {top.name, shoes.name} & set(names(everything))


@pytest.mark.parametrize(
    "bad",
    ["", "nope", "a,b", ",".join(str(uuid.uuid4()) for _ in range(6))],
)
async def test_bad_product_ids_are_rejected(api, bad):
    assert (await api.get("/recommend", params={"product_ids": bad})).status_code == 422


async def test_unknown_products_are_404_and_duplicates_are_ignored(api, adb):
    p = await make_product(adb, category=C.top)
    unknown = uuid.uuid4()
    r = await api.get("/recommend", params={"product_ids": f"{p.id},{unknown}"})
    assert r.status_code == 404 and str(unknown) in r.json()["detail"]
    assert (await api.get("/recommend", params={"product_ids": f"{p.id},{p.id}"})).status_code == 200
    assert (await api.get("/recommend")).status_code == 422
