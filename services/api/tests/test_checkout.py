import re
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update

from app.api import orders
from app.models import Order
from tests.helpers import ADMIN_HEADERS, make_product, make_session


def add(api, sid, product, **extra):
    return api.post("/cart/add", json={"session_id": sid, "product_id": str(product.id), **extra})


def checkout(api, sid, key=None):
    body = {"session_id": sid}
    if key:
        body["idempotency_key"] = str(key)
    return api.post("/checkout", json=body)


async def stock_of(adb, product) -> int:
    await adb.refresh(product)
    return product.stock


async def order_count(adb) -> int:
    return await adb.scalar(select(func.count()).select_from(Order))


async def test_checkout_places_an_order_for_the_whole_cart_and_empties_it(api, adb):
    shirt = await make_product(
        adb, name="Linen Shirt", price_pkr=2000, sale_price_pkr=1500, sizes=["S", "M"], stock=5
    )
    hat = await make_product(adb, name="Straw Hat", price_pkr=900, sizes=[], colors=[], stock=3)
    sid = await make_session(api)
    await add(api, sid, shirt, size="M", quantity=2)
    await add(api, sid, hat)

    r = await checkout(api, sid)

    assert r.status_code == 201
    order = r.json()
    assert order["session_id"] == sid
    assert re.fullmatch(f"[{orders.CODE_ALPHABET}]{{6}}", order["pickup_code"])
    assert order["item_count"] == 3 and order["subtotal_pkr"] == 2 * 1500 + 900
    lines = {
        i["product_name"]: i for i in order["items"]
    }  # (line order follows the cart's timestamps, which a test cannot vary)
    assert len(lines) == 2
    assert (lines["Linen Shirt"]["size"], lines["Linen Shirt"]["quantity"]) == ("M", 2)
    assert (lines["Linen Shirt"]["unit_price_pkr"], lines["Linen Shirt"]["line_total_pkr"]) == (
        1500,
        3000,
    )  # the sale price
    assert (
        lines["Straw Hat"]["size"],
        lines["Straw Hat"]["quantity"],
        lines["Straw Hat"]["line_total_pkr"],
    ) == (None, 1, 900)
    assert lines["Linen Shirt"]["product_id"] == str(shirt.id)
    # The cart is empty and the items are out of stock.
    cart = (await api.get(f"/cart/{sid}")).json()
    assert cart["items"] == [] and cart["item_count"] == 0 and cart["subtotal_pkr"] == 0
    assert await stock_of(adb, shirt) == 3 and await stock_of(adb, hat) == 2


async def test_buying_the_last_items_takes_stock_to_zero(api, adb):
    p = await make_product(adb, sizes=["M"], stock=2)
    sid = await make_session(api)
    await add(api, sid, p, quantity=2)

    assert (await checkout(api, sid)).status_code == 201
    assert await stock_of(adb, p) == 0


async def test_an_empty_cart_cannot_be_checked_out(api, adb):
    sid = await make_session(api)
    r = await checkout(api, sid)  # no cart yet
    assert r.status_code == 409 and r.json()["detail"] == "Your cart is empty"

    before = await order_count(adb)
    p = await make_product(adb, sizes=["M"])
    await add(api, sid, p)
    assert (await checkout(api, sid)).status_code == 201
    assert (await checkout(api, sid)).status_code == 409  # emptied by the first
    assert await order_count(adb) - before == 1


async def test_not_enough_stock_refuses_the_whole_checkout_and_changes_nothing(api, adb):
    fine = await make_product(adb, name="Fine Item", sizes=["M"], stock=5)
    scarce = await make_product(adb, name="Scarce Item", sizes=["M"], stock=3)
    sid = await make_session(api)
    await add(api, sid, fine, quantity=2)
    await add(api, sid, scarce, quantity=3)
    scarce.stock = 1  # someone else bought most of it meanwhile
    await adb.flush()
    before = await order_count(adb)

    r = await checkout(api, sid)

    assert r.status_code == 409
    assert r.json()["detail"] == "Not enough stock. Scarce Item: only 1 left"
    assert await order_count(adb) == before
    assert await stock_of(adb, fine) == 5 and await stock_of(adb, scarce) == 1
    assert (await api.get(f"/cart/{sid}")).json()["item_count"] == 5  # the cart is untouched


async def test_sold_out_items_are_named_as_sold_out(api, adb):
    p = await make_product(adb, name="Gone Item", sizes=["M"], stock=2)
    sid = await make_session(api)
    await add(api, sid, p)
    p.stock = 0
    await adb.flush()

    r = await checkout(api, sid)

    assert r.status_code == 409 and r.json()["detail"] == "Not enough stock. Gone Item: sold out"


async def test_stock_is_counted_across_all_lines_of_a_product(api, adb):
    p = await make_product(adb, name="Two Sizes", sizes=["S", "M"], stock=4)
    sid = await make_session(api)
    await add(api, sid, p, size="S", quantity=2)
    await add(api, sid, p, size="M", quantity=2)
    p.stock = 3  # each line alone fits, together they do not
    await adb.flush()

    r = await checkout(api, sid)

    assert r.status_code == 409 and "Two Sizes: only 3 left" in r.json()["detail"]


async def test_the_order_keeps_the_prices_it_was_placed_at(api, adb):
    p = await make_product(adb, name="Price Test", price_pkr=1000, sizes=["M"], stock=5)
    sid = await make_session(api)
    await add(api, sid, p)
    placed = (await checkout(api, sid)).json()

    p.price_pkr = 5000
    p.name = "Renamed"
    await adb.flush()

    listed = (await api.get("/orders", headers=ADMIN_HEADERS)).json()
    mine = next(o for o in listed if o["id"] == placed["id"])
    assert mine["subtotal_pkr"] == 1000
    assert (mine["items"][0]["product_name"], mine["items"][0]["unit_price_pkr"]) == ("Price Test", 1000)


async def test_orders_survive_the_product_being_deleted(api, adb):
    p = await make_product(adb, name="Short Lived", sizes=["M"], stock=5)
    pid = p.id
    sid = await make_session(api)
    await add(api, sid, p)
    placed = (await checkout(api, sid)).json()

    assert (
        await api.delete(f"/products/{pid}", headers=ADMIN_HEADERS)
    ).status_code == 204  # not in a cart now

    listed = (await api.get("/orders", headers=ADMIN_HEADERS)).json()
    assert next(o for o in listed if o["id"] == placed["id"])["items"][0]["product_name"] == "Short Lived"


async def test_a_retry_with_the_same_key_returns_the_same_order_once(api, adb):
    p = await make_product(adb, sizes=["M"], stock=5)
    sid = await make_session(api)
    await add(api, sid, p, quantity=2)
    key = uuid.uuid4()
    before = await order_count(adb)

    first = await checkout(api, sid, key)
    again = await checkout(api, sid, key)

    assert first.status_code == 201 and again.status_code == 200
    assert again.json() == first.json()
    assert await order_count(adb) - before == 1 and await stock_of(adb, p) == 3  # taken off once


async def test_a_retry_returns_the_order_even_after_the_cart_has_new_items(api, adb):
    p = await make_product(adb, sizes=["M"], stock=9)
    sid = await make_session(api)
    await add(api, sid, p)
    key = uuid.uuid4()
    first = (await checkout(api, sid, key)).json()
    await add(api, sid, p, quantity=3)  # the shopper carries on

    again = await checkout(api, sid, key)

    assert again.json()["id"] == first["id"]
    assert (await api.get(f"/cart/{sid}")).json()["item_count"] == 3  # the new items are not swept in


async def test_a_new_key_places_a_new_order_with_its_own_code(api, adb):
    p = await make_product(adb, sizes=["M"], stock=9)
    sid = await make_session(api)
    await add(api, sid, p)
    a = (await checkout(api, sid, uuid.uuid4())).json()
    await add(api, sid, p, quantity=2)
    b = (await checkout(api, sid, uuid.uuid4())).json()

    assert a["id"] != b["id"] and a["pickup_code"] != b["pickup_code"]
    assert b["item_count"] == 2 and await stock_of(adb, p) == 6


async def test_the_same_key_in_another_session_is_a_different_checkout(api, adb):
    p = await make_product(adb, sizes=["M"], stock=9)
    s1, s2 = await make_session(api), await make_session(api)
    await add(api, s1, p)
    await add(api, s2, p)
    key = uuid.uuid4()

    a = await checkout(api, s1, key)
    b = await checkout(api, s2, key)

    assert a.status_code == b.status_code == 201 and a.json()["id"] != b.json()["id"]


async def test_one_session_cannot_check_out_another_sessions_cart(api, adb):
    p = await make_product(adb, sizes=["M"], stock=9)
    mine, theirs = await make_session(api), await make_session(api)
    await add(api, theirs, p)

    assert (await checkout(api, mine)).status_code == 409
    assert (await api.get(f"/cart/{theirs}")).json()["item_count"] == 1


async def test_checkout_validates_ids(api):
    assert (await checkout(api, str(uuid.uuid4()))).status_code == 404
    assert (await api.post("/checkout", json={"session_id": "nope"})).status_code == 422
    assert (await api.post("/checkout", json={})).status_code == 422
    bad_key = await api.post("/checkout", json={"session_id": str(uuid.uuid4()), "idempotency_key": "x"})
    assert bad_key.status_code == 422


def test_pickup_codes_are_unambiguous_and_the_right_length():
    codes = {orders._new_code() for _ in range(500)}
    assert all(len(c) == 6 and set(c) <= set(orders.CODE_ALPHABET) for c in codes)
    assert not set("0O1ILS25Z") & set(orders.CODE_ALPHABET)
    assert len(codes) > 490  # random, not a counter


async def test_a_code_collision_is_retried(api, adb, monkeypatch):
    p = await make_product(adb, sizes=["M"], stock=9)
    s1, s2 = await make_session(api), await make_session(api)
    await add(api, s1, p)
    await add(api, s2, p)
    first = (await checkout(api, s1)).json()["pickup_code"]
    codes = iter([first, first, "ABCDEF"])  # twice the taken code, then a free one
    monkeypatch.setattr(orders, "_new_code", lambda: next(codes))

    second = (await checkout(api, s2)).json()

    assert second["pickup_code"] == "ABCDEF"


async def test_listing_orders_needs_the_admin_key(api):
    assert (await api.get("/orders")).status_code == 401
    assert (await api.get("/orders", headers={"X-Admin-Key": "nope"})).status_code == 401


async def test_orders_list_newest_first_and_find_by_code(api, adb):
    p = await make_product(adb, sizes=["M"], stock=9)
    placed = []
    for _ in range(3):
        sid = await make_session(api)
        await add(api, sid, p)
        placed.append((await checkout(api, sid)).json())
    # Tests share one transaction, so every order got the same now(); space them out as real ones would be.
    base = datetime.now(UTC)
    for n, order in enumerate(placed):
        await adb.execute(
            update(Order)
            .where(Order.id == uuid.UUID(order["id"]))
            .values(created_at=base + timedelta(minutes=n))
        )

    listed = (await api.get("/orders", headers=ADMIN_HEADERS)).json()
    ids = [o["id"] for o in listed]
    assert ids[:3] == [o["id"] for o in reversed(placed)]

    middle = placed[1]["pickup_code"]
    for typed in (middle, middle.lower(), f"  {middle.lower()} "):
        found = (await api.get("/orders", params={"code": typed}, headers=ADMIN_HEADERS)).json()
        assert [o["id"] for o in found] == [placed[1]["id"]]
    assert (await api.get("/orders", params={"code": "ZZZZZZ"}, headers=ADMIN_HEADERS)).json() == []
    assert len((await api.get("/orders", params={"limit": 2}, headers=ADMIN_HEADERS)).json()) == 2
    assert (await api.get("/orders", params={"limit": 0}, headers=ADMIN_HEADERS)).status_code == 422
