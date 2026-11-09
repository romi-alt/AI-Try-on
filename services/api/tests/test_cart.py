import uuid

from tests.helpers import make_product, make_session


def add(api, session_id, product, **extra):
    return api.post("/cart/add", json={"session_id": session_id, "product_id": str(product.id), **extra})


async def test_add_creates_cart_and_prices_with_the_sale_price(api, adb):
    p = await make_product(adb, price_pkr=5000, sale_price_pkr=4000, sizes=["S", "M"])
    sid = await make_session(api)

    r = await add(api, sid, p, size="M", quantity=2)

    assert r.status_code == 200
    cart = r.json()
    assert cart["session_id"] == sid and cart["cart_id"]
    (item,) = cart["items"]
    assert item["product"]["id"] == str(p.id) and item["product"]["name"] == p.name
    assert (item["size"], item["color"], item["quantity"]) == ("M", "Ivory", 2)
    assert item["unit_price_pkr"] == 4000 and item["line_total_pkr"] == 8000
    assert cart["item_count"] == 2 and cart["subtotal_pkr"] == 8000


async def test_adding_the_same_variant_merges_into_one_line(api, adb):
    p = await make_product(adb, sizes=["S", "M"], stock=10)
    sid = await make_session(api)

    await add(api, sid, p, size="S", quantity=1)
    r = await add(api, sid, p, size="S", quantity=3)

    (item,) = r.json()["items"]
    assert item["quantity"] == 4


async def test_different_sizes_or_colors_are_separate_lines(api, adb):
    p = await make_product(
        adb,
        sizes=["S", "M"],
        colors=[{"name": "Ivory", "hex": "#efe6d2"}, {"name": "Black", "hex": "#000000"}],
        stock=10,
    )
    sid = await make_session(api)

    await add(api, sid, p, size="S", color="Ivory")
    await add(api, sid, p, size="M", color="Ivory")
    r = await add(api, sid, p, size="S", color="Black")

    lines = {(i["size"], i["color"]): i["quantity"] for i in r.json()["items"]}
    assert lines == {("S", "Ivory"): 1, ("M", "Ivory"): 1, ("S", "Black"): 1}
    assert r.json()["item_count"] == 3


async def test_multiple_products_total_up(api, adb):
    a = await make_product(adb, price_pkr=1000, sizes=["M"])
    b = await make_product(adb, price_pkr=2500, sale_price_pkr=2000, sizes=["M"])
    sid = await make_session(api)

    await add(api, sid, a, quantity=2)
    r = await add(api, sid, b)

    assert r.json()["subtotal_pkr"] == 2 * 1000 + 2000
    assert len(r.json()["items"]) == 2


async def test_single_option_size_and_color_are_filled_in(api, adb):
    p = await make_product(adb, sizes=["One Size"], colors=[{"name": "Black", "hex": "#000000"}])
    sid = await make_session(api)

    r = await add(api, sid, p)

    (item,) = r.json()["items"]
    assert (item["size"], item["color"]) == ("One Size", "Black")


async def test_product_without_options_needs_none(api, adb):
    p = await make_product(adb, sizes=[], colors=[])
    sid = await make_session(api)

    r = await add(api, sid, p)

    (item,) = r.json()["items"]
    assert item["size"] is None and item["color"] is None


async def test_size_is_required_when_there_is_a_choice(api, adb):
    p = await make_product(adb, sizes=["S", "M"])
    sid = await make_session(api)

    r = await add(api, sid, p)

    assert r.status_code == 422 and "size is required" in r.json()["detail"]


async def test_unknown_size_or_color_is_rejected(api, adb):
    p = await make_product(adb, sizes=["S", "M"])
    sid = await make_session(api)

    bad_size = await add(api, sid, p, size="XXL")
    bad_color = await add(api, sid, p, size="S", color="Neon")

    assert bad_size.status_code == 422 and "Invalid size" in bad_size.json()["detail"]
    assert bad_color.status_code == 422 and "Invalid color" in bad_color.json()["detail"]
    assert (await api.get(f"/cart/{sid}")).json()["items"] == []


async def test_stock_limit_is_enforced_across_merges_and_variants(api, adb):
    p = await make_product(adb, sizes=["S", "M"], stock=3)
    sid = await make_session(api)

    assert (await add(api, sid, p, size="S", quantity=2)).status_code == 200
    # 2 already in the cart (any size) + 2 more would exceed stock of 3.
    over = await add(api, sid, p, size="M", quantity=2)
    assert over.status_code == 409 and "Only 3 in stock" in over.json()["detail"]
    assert (await add(api, sid, p, size="M", quantity=1)).status_code == 200

    cart = (await api.get(f"/cart/{sid}")).json()
    assert cart["item_count"] == 3


async def test_out_of_stock_product_cannot_be_added(api, adb):
    p = await make_product(adb, stock=0, sizes=["M"])
    sid = await make_session(api)

    r = await add(api, sid, p)

    assert r.status_code == 409 and r.json()["detail"] == "Out of stock"


async def test_add_validates_quantity(api, adb):
    p = await make_product(adb, sizes=["M"])
    sid = await make_session(api)
    for qty in (0, -1, 11):
        assert (await add(api, sid, p, quantity=qty)).status_code == 422, qty


async def test_add_with_unknown_session_or_product_is_404(api, adb):
    p = await make_product(adb, sizes=["M"])
    sid = await make_session(api)

    no_session = await api.post("/cart/add", json={"session_id": str(uuid.uuid4()), "product_id": str(p.id)})
    no_product = await api.post("/cart/add", json={"session_id": sid, "product_id": str(uuid.uuid4())})

    assert no_session.status_code == 404 and "Session" in no_session.json()["detail"]
    assert no_product.status_code == 404 and "Product" in no_product.json()["detail"]


async def test_add_rejects_malformed_body(api):
    assert (await api.post("/cart/add", json={})).status_code == 422
    assert (await api.post("/cart/add", json={"session_id": "x", "product_id": "y"})).status_code == 422


async def test_get_cart_for_a_new_session_is_empty(api):
    sid = await make_session(api)

    r = await api.get(f"/cart/{sid}")

    assert r.status_code == 200
    assert r.json() == {"session_id": sid, "cart_id": None, "items": [], "item_count": 0, "subtotal_pkr": 0}


async def test_get_cart_returns_what_was_added(api, adb):
    p = await make_product(adb, price_pkr=1500, sizes=["M"])
    sid = await make_session(api)
    added = (await add(api, sid, p, quantity=2)).json()

    r = await api.get(f"/cart/{sid}")

    assert r.status_code == 200
    assert r.json() == added
    assert r.json()["subtotal_pkr"] == 3000


async def test_carts_are_isolated_per_session(api, adb):
    p = await make_product(adb, sizes=["M"])
    s1, s2 = await make_session(api), await make_session(api)

    await add(api, s1, p)

    assert (await api.get(f"/cart/{s1}")).json()["item_count"] == 1
    assert (await api.get(f"/cart/{s2}")).json()["item_count"] == 0


async def test_get_cart_unknown_session_is_404_and_bad_id_is_422(api):
    assert (await api.get(f"/cart/{uuid.uuid4()}")).status_code == 404
    assert (await api.get("/cart/not-a-uuid")).status_code == 422


async def test_cart_reflects_current_prices(api, adb):
    p = await make_product(adb, price_pkr=1000, sale_price_pkr=None, sizes=["M"])
    sid = await make_session(api)
    await add(api, sid, p)

    p.sale_price_pkr = 700
    await adb.flush()

    assert (await api.get(f"/cart/{sid}")).json()["subtotal_pkr"] == 700
