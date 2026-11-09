import uuid

import pytest
from sqlalchemy import select

from app.models import Order
from tests.helpers import ADMIN_HEADERS, make_product, make_session


async def place(api, adb, *lines, stock=10):
    """Place an order for `lines` of (size, quantity, product-or-None); returns (order json, [products])."""
    sid = await make_session(api)
    products = []
    for size, quantity, product in lines:
        product = product or await make_product(adb, sizes=["S", "M"], stock=stock)
        products.append(product)
        r = await api.post(
            "/cart/add",
            json={"session_id": sid, "product_id": str(product.id), "size": size, "quantity": quantity},
        )
        assert r.status_code == 200, r.text
    r = await api.post("/checkout", json={"session_id": sid, "idempotency_key": str(uuid.uuid4())})
    assert r.status_code == 201, r.text
    return r.json(), products


def set_status(api, order, status, headers=ADMIN_HEADERS):
    return api.patch(f"/orders/{order['id']}", json={"status": status}, headers=headers)


async def stock_of(adb, product) -> int:
    await adb.refresh(product)
    return product.stock


async def test_a_new_order_is_placed_and_unchanged(api, adb):
    order, _ = await place(api, adb, ("S", 1, None))
    assert order["status"] == "placed" and order["status_changed_at"] is None


async def test_collecting_an_order_marks_it_and_leaves_stock_alone(api, adb):
    order, (p,) = await place(api, adb, ("S", 3, None), stock=10)
    assert await stock_of(adb, p) == 7

    r = await set_status(api, order, "collected")

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "collected" and body["status_changed_at"] is not None
    assert body["id"] == order["id"] and body["pickup_code"] == order["pickup_code"]
    assert [i["quantity"] for i in body["items"]] == [3]  # the order itself is untouched
    assert await stock_of(adb, p) == 7


async def test_cancelling_puts_every_item_back_into_stock(api, adb):
    shirt = await make_product(adb, sizes=["S", "M"], stock=10)
    hat = await make_product(adb, sizes=["M"], stock=4)
    order, _ = await place(api, adb, ("S", 2, shirt), ("M", 3, shirt), ("M", 1, hat))
    assert (await stock_of(adb, shirt), await stock_of(adb, hat)) == (5, 3)

    r = await set_status(api, order, "cancelled")

    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert r.json()["status_changed_at"] is not None
    assert (await stock_of(adb, shirt), await stock_of(adb, hat)) == (
        10,
        4,
    )  # both of the shirt's lines came back


async def test_repeating_the_same_change_does_nothing_more(api, adb):
    order, (p,) = await place(api, adb, ("S", 2, None), stock=10)

    first = await set_status(api, order, "cancelled")
    again = await set_status(api, order, "cancelled")

    assert first.status_code == again.status_code == 200
    assert again.json() == first.json()  # including the original change time
    assert await stock_of(adb, p) == 10  # returned once, not twice

    other, _ = await place(api, adb, ("S", 1, None))
    one = await set_status(api, other, "collected")
    two = await set_status(api, other, "collected")
    assert two.status_code == 200 and two.json() == one.json()


@pytest.mark.parametrize(("first", "then"), [("collected", "cancelled"), ("cancelled", "collected")])
async def test_a_closed_order_cannot_be_switched_to_the_other_state(api, adb, first, then):
    order, (p,) = await place(api, adb, ("S", 2, None), stock=10)
    await set_status(api, order, first)
    stock_after_first = await stock_of(adb, p)

    r = await set_status(api, order, then)

    assert r.status_code == 409
    assert r.json()["detail"] == f"This order is already {first} and cannot be marked {then}"
    assert await stock_of(adb, p) == stock_after_first
    shown = (await api.get("/orders", params={"code": order["pickup_code"]}, headers=ADMIN_HEADERS)).json()
    assert shown[0]["status"] == first


async def test_cancelling_skips_a_product_that_has_since_been_deleted(api, adb):
    keep = await make_product(adb, sizes=["M"], stock=5)
    gone = await make_product(adb, sizes=["M"], stock=5)
    order, _ = await place(api, adb, ("M", 1, keep), ("M", 2, gone))
    assert (await api.delete(f"/products/{gone.id}", headers=ADMIN_HEADERS)).status_code == 204

    r = await set_status(api, order, "cancelled")

    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert await stock_of(adb, keep) == 5


async def test_cancelling_adds_to_whatever_the_stock_is_now(api, adb):
    order, (p,) = await place(api, adb, ("S", 2, None), stock=5)  # stock 3
    p.stock = 20  # restocked by hand since
    await adb.flush()

    await set_status(api, order, "cancelled")

    assert await stock_of(adb, p) == 22


async def test_only_collected_or_cancelled_can_be_requested(api, adb):
    order, _ = await place(api, adb, ("S", 1, None))
    for bad in ("placed", "refunded", "", None, 3):
        r = await api.patch(f"/orders/{order['id']}", json={"status": bad}, headers=ADMIN_HEADERS)
        assert r.status_code == 422, bad
    assert (await api.patch(f"/orders/{order['id']}", json={}, headers=ADMIN_HEADERS)).status_code == 422


async def test_changing_an_order_needs_the_admin_key(api, adb):
    order, (p,) = await place(api, adb, ("S", 1, None), stock=10)
    body = {"status": "cancelled"}
    assert (await api.patch(f"/orders/{order['id']}", json=body)).status_code == 401
    assert (
        await api.patch(f"/orders/{order['id']}", json=body, headers={"X-Admin-Key": "nope"})
    ).status_code == 401
    assert await stock_of(adb, p) == 9  # nothing was returned
    row = await adb.scalar(select(Order).where(Order.id == uuid.UUID(order["id"])))
    await adb.refresh(row)
    assert row.status == "placed"


async def test_unknown_and_malformed_order_ids(api):
    assert (
        await api.patch(f"/orders/{uuid.uuid4()}", json={"status": "collected"}, headers=ADMIN_HEADERS)
    ).status_code == 404
    assert (
        await api.patch("/orders/nope", json={"status": "collected"}, headers=ADMIN_HEADERS)
    ).status_code == 422


async def test_orders_can_be_listed_by_status(api, adb):
    waiting, _ = await place(api, adb, ("S", 1, None))
    done, _ = await place(api, adb, ("S", 1, None))
    dropped, _ = await place(api, adb, ("S", 1, None))
    await set_status(api, done, "collected")
    await set_status(api, dropped, "cancelled")

    def ids(status):
        return api.get("/orders", params={"status": status, "limit": 200}, headers=ADMIN_HEADERS)

    assert waiting["id"] in [o["id"] for o in (await ids("placed")).json()]
    assert done["id"] not in [o["id"] for o in (await ids("placed")).json()]
    assert [o["id"] for o in (await ids("collected")).json() if o["id"] == done["id"]] == [done["id"]]
    assert all(o["status"] == "cancelled" for o in (await ids("cancelled")).json())
    assert dropped["id"] in [o["id"] for o in (await ids("cancelled")).json()]
    assert (await api.get("/orders", params={"status": "bogus"}, headers=ADMIN_HEADERS)).status_code == 422
    # a closed order is still found by its code, whatever its state
    found = (await api.get("/orders", params={"code": done["pickup_code"]}, headers=ADMIN_HEADERS)).json()
    assert [o["status"] for o in found] == ["collected"]


async def test_a_checkout_retry_after_the_order_was_cancelled_returns_it_not_a_new_one(api, adb):
    p = await make_product(adb, sizes=["S"], stock=10)
    sid = await make_session(api)
    await api.post("/cart/add", json={"session_id": sid, "product_id": str(p.id), "size": "S"})
    key = str(uuid.uuid4())
    first = (await api.post("/checkout", json={"session_id": sid, "idempotency_key": key})).json()
    await set_status(api, first, "cancelled")

    again = await api.post("/checkout", json={"session_id": sid, "idempotency_key": key})

    assert again.status_code == 200
    assert again.json()["id"] == first["id"] and again.json()["status"] == "cancelled"
    assert await stock_of(adb, p) == 10


async def test_a_cancelled_order_can_be_ordered_again_from_a_fresh_cart(api, adb):
    order, (p,) = await place(api, adb, ("S", 10, None), stock=10)  # takes all the stock
    sid = await make_session(api)
    add = await api.post("/cart/add", json={"session_id": sid, "product_id": str(p.id), "size": "S"})
    assert add.status_code == 409  # sold out while the order stands

    await set_status(api, order, "cancelled")

    add = await api.post("/cart/add", json={"session_id": sid, "product_id": str(p.id), "size": "S"})
    assert add.status_code == 200  # back in stock
