from app.models import ProductCategory
from tests.helpers import make_product


async def test_catalog_page_shape_and_computed_price_fields(api, adb, token):
    await make_product(adb, name=f"{token} Kurta", price_pkr=5000, sale_price_pkr=4000)

    r = await api.get("/catalog", params={"search": token})

    assert r.status_code == 200
    body = r.json()
    assert (body["total"], body["page"], body["page_size"], body["pages"]) == (1, 1, 20, 1)
    (item,) = body["items"]
    assert item["name"] == f"{token} Kurta"
    assert item["on_sale"] is True
    assert item["current_price_pkr"] == 4000
    assert {"id", "category", "price_pkr", "sale_price_pkr", "sizes", "colors", "stock"} <= set(item)
    assert "embedding" not in item


async def test_catalog_filters_by_category(api, adb, token):
    await make_product(adb, name=f"{token} tee", category=ProductCategory.top)
    await make_product(adb, name=f"{token} heels", category=ProductCategory.shoes)

    r = await api.get("/catalog", params={"search": token, "category": "shoes"})

    assert [i["name"] for i in r.json()["items"]] == [f"{token} heels"]
    assert r.json()["total"] == 1


async def test_catalog_on_sale_filter_true_and_false(api, adb, token):
    await make_product(adb, name=f"{token} discounted", price_pkr=1000, sale_price_pkr=800)
    # A sale price equal to the price is not a discount.
    await make_product(adb, name=f"{token} same-price", price_pkr=1000, sale_price_pkr=1000)
    await make_product(adb, name=f"{token} regular", price_pkr=1000, sale_price_pkr=None)

    on = await api.get("/catalog", params={"search": token, "on_sale": "true"})
    off = await api.get("/catalog", params={"search": token, "on_sale": "false"})
    both = await api.get("/catalog", params={"search": token})

    assert [i["name"] for i in on.json()["items"]] == [f"{token} discounted"]
    assert sorted(i["name"] for i in off.json()["items"]) == [f"{token} regular", f"{token} same-price"]
    assert both.json()["total"] == 3
    assert all(i["on_sale"] is False for i in off.json()["items"])


async def test_catalog_search_is_case_insensitive(api, adb, token):
    await make_product(adb, name=f"{token} Linen Camp Shirt")

    r = await api.get("/catalog", params={"search": f"{token.upper()} linen"})

    assert r.json()["total"] == 1


async def test_catalog_search_treats_like_wildcards_literally(api, adb, token):
    await make_product(adb, name=f"{token}-1")
    await make_product(adb, name=f"{token}A1")
    await make_product(adb, name=f"{token}_1")

    # "_" must not match any single character, and "%" must not match everything.
    underscore = await api.get("/catalog", params={"search": f"{token}_1"})
    percent = await api.get("/catalog", params={"search": f"{token}%"})

    assert [i["name"] for i in underscore.json()["items"]] == [f"{token}_1"]
    assert percent.json()["total"] == 0


async def test_catalog_blank_search_means_no_filter(api, adb, token):
    await make_product(adb, name=f"{token} a")
    blank = await api.get("/catalog", params={"search": "   ", "page_size": 1})
    unfiltered = await api.get("/catalog", params={"page_size": 1})
    assert blank.json()["total"] == unfiltered.json()["total"] >= 1


async def test_catalog_pagination_covers_every_item_exactly_once(api, adb, token):
    for i in range(5):
        await make_product(adb, name=f"{token} item {i}")

    pages = [
        await api.get("/catalog", params={"search": token, "page": p, "page_size": 2}) for p in (1, 2, 3)
    ]

    assert [len(p.json()["items"]) for p in pages] == [2, 2, 1]
    assert all(p.json()["total"] == 5 and p.json()["pages"] == 3 for p in pages)
    names = [i["name"] for p in pages for i in p.json()["items"]]
    assert len(names) == len(set(names)) == 5

    beyond = await api.get("/catalog", params={"search": token, "page": 4, "page_size": 2})
    assert beyond.status_code == 200
    assert beyond.json()["items"] == [] and beyond.json()["total"] == 5


async def test_catalog_combines_filters(api, adb, token):
    await make_product(adb, name=f"{token} a", category=ProductCategory.bag, price_pkr=100, sale_price_pkr=50)
    await make_product(adb, name=f"{token} b", category=ProductCategory.bag, price_pkr=100)
    await make_product(adb, name=f"{token} c", category=ProductCategory.top, price_pkr=100, sale_price_pkr=50)

    r = await api.get("/catalog", params={"search": token, "category": "bag", "on_sale": "true"})

    assert [i["name"] for i in r.json()["items"]] == [f"{token} a"]


async def test_catalog_with_no_matches_is_an_empty_page(api, token):
    r = await api.get("/catalog", params={"search": token})
    assert r.status_code == 200
    assert r.json() == {"items": [], "total": 0, "page": 1, "page_size": 20, "pages": 0}


async def test_catalog_rejects_invalid_params(api):
    for params in (
        {"page": 0},
        {"page_size": 0},
        {"page_size": 101},
        {"category": "hats"},
        {"on_sale": "maybe"},
        {"search": "x" * 101},
    ):
        r = await api.get("/catalog", params=params)
        assert r.status_code == 422, params
