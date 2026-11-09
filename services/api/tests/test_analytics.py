import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models import Cart, CartItem, JobStatus, KioskSession, Order, OrderItem, TryOnJob
from tests.helpers import ADMIN_HEADERS, make_product

HOURS = timedelta(hours=1)


def ago(**kw) -> datetime:
    return datetime.now(UTC) - timedelta(**kw)


async def session(adb) -> uuid.UUID:
    s = KioskSession(consent_given=True)
    adb.add(s)
    await adb.flush()
    return s.id


async def job(adb, sid, products, *, recommended=(), status=JobStatus.done, created=None) -> TryOnJob:
    j = TryOnJob(
        session_id=sid,
        product_ids=[p.id for p in products],
        recommended_product_ids=[p.id for p in recommended],
        person_image_key="captures/x.webp",
        status=status,
        created_at=created or ago(hours=2),
    )
    adb.add(j)
    await adb.flush()
    return j


async def in_cart(adb, sid, product, *, created=None):
    cart = await adb.scalar(select(Cart).where(Cart.session_id == sid))
    if cart is None:
        cart = Cart(session_id=sid)
        adb.add(cart)
        await adb.flush()
    adb.add(CartItem(cart_id=cart.id, product_id=product.id, quantity=1, created_at=created or ago(hours=1)))
    await adb.flush()


async def ordered(adb, sid, product, *, created=None):
    o = Order(
        session_id=sid,
        pickup_code=uuid.uuid4().hex[:6].upper(),
        item_count=1,
        subtotal_pkr=100,
        created_at=created or ago(hours=1),
    )
    o.items.append(
        OrderItem(
            position=0,
            product_id=product.id,
            product_name=product.name,
            garment_image_url="http://x/y.png",
            quantity=1,
            unit_price_pkr=100,
            line_total_pkr=100,
        )
    )
    adb.add(o)
    await adb.flush()


async def get(api, **params):
    r = await api.get("/admin/analytics", params={"limit": 100, **params}, headers=ADMIN_HEADERS)
    assert r.status_code == 200, r.text
    return r.json()


def row(body, product):
    return next((p for p in body["products"] if p["product_id"] == str(product.id)), None)


async def test_requires_the_admin_key(api):
    assert (await api.get("/admin/analytics")).status_code == 401


async def test_validates_the_period(api):
    for days in (0, 366):
        r = await api.get("/admin/analytics", params={"days": days}, headers=ADMIN_HEADERS)
        assert r.status_code == 422


async def test_counts_tryons_and_cart_adds_per_product(api, adb):
    a, b = await make_product(adb), await make_product(adb)
    s1, s2, s3 = await session(adb), await session(adb), await session(adb)
    await job(adb, s1, [a, b])  # a and b tried together; only a goes in the cart
    await in_cart(adb, s1, a)
    await job(adb, s2, [a])  # tried, nothing added
    await job(adb, s3, [a], status=JobStatus.failed)  # failed looks do not count
    await job(adb, s3, [a], status=JobStatus.queued)
    await job(adb, s3, [a], created=ago(days=40))  # outside the 30 day window

    body = await get(api)

    assert (row(body, a)["tryons"], row(body, a)["added_to_cart"], row(body, a)["cart_rate"]) == (2, 1, 0.5)
    assert (row(body, b)["tryons"], row(body, b)["added_to_cart"], row(body, b)["cart_rate"]) == (1, 0, 0.0)
    assert row(body, a)["category"] == "top" and row(body, a)["name"] == a.name


async def test_the_window_follows_days(api, adb):
    a = await make_product(adb)
    s = await session(adb)
    await job(adb, s, [a], created=ago(days=40))
    assert row(await get(api, days=30), a) is None
    assert row(await get(api, days=60), a)["tryons"] == 1


async def test_a_purchase_still_counts_after_checkout_emptied_the_cart(api, adb):
    a = await make_product(adb)
    s = await session(adb)
    await job(adb, s, [a])
    await ordered(adb, s, a)
    assert row(await get(api), a)["added_to_cart"] == 1


async def test_something_added_before_the_look_does_not_count(api, adb):
    a = await make_product(adb)
    s = await session(adb)
    await in_cart(adb, s, a, created=ago(hours=5))
    await ordered(adb, s, a, created=ago(hours=4))
    await job(adb, s, [a], created=ago(hours=2))
    assert row(await get(api), a)["added_to_cart"] == 0


async def test_another_sessions_cart_does_not_count(api, adb):
    a = await make_product(adb)
    s1, s2 = await session(adb), await session(adb)
    await job(adb, s1, [a])
    await in_cart(adb, s2, a)
    assert row(await get(api), a)["added_to_cart"] == 0


async def test_overall_rate_is_per_look(api, adb):
    a, b = await make_product(adb), await make_product(adb)
    before = await get(api)
    s1, s2, s3 = await session(adb), await session(adb), await session(adb)
    await job(adb, s1, [a, b])
    await in_cart(adb, s1, a)
    await in_cart(adb, s1, b)  # two items from one look is still one converted look
    await job(adb, s2, [a])
    await job(adb, s3, [b])
    await ordered(adb, s3, b)

    after = await get(api)

    assert after["tryons"] - before["tryons"] == 3
    assert after["tryons_with_cart"] - before["tryons_with_cart"] == 2
    assert after["cart_rate"] == round(after["tryons_with_cart"] / after["tryons"], 4)


async def test_top_pairings(api, adb):
    base, rec, other = await make_product(adb), await make_product(adb), await make_product(adb)
    s1, s2, s3 = await session(adb), await session(adb), await session(adb)
    await job(adb, s1, [base, rec], recommended=[rec])
    await in_cart(adb, s1, rec)
    await job(adb, s2, [base, rec], recommended=[rec])  # same pairing again, not bought
    await job(adb, s3, [base, other])  # no suggestion used: not a pairing

    body = await get(api)

    mine = [p for p in body["pairings"] if p["base_product_id"] == str(base.id)]
    assert len(mine) == 1
    assert (mine[0]["recommended_product_id"], mine[0]["tryons"], mine[0]["added_to_cart"]) == (
        str(rec.id),
        2,
        1,
    )
    assert mine[0]["base_name"] == base.name and mine[0]["recommended_name"] == rec.name
    # a suggestion is never paired with itself
    assert not [p for p in body["pairings"] if p["base_product_id"] == p["recommended_product_id"]]


async def test_pairings_are_ranked_by_cart_adds_then_tries(api, adb):
    base, r1, r2 = await make_product(adb), await make_product(adb), await make_product(adb)
    for rec, carts in ((r1, False), (r1, False), (r2, True)):
        s = await session(adb)
        await job(adb, s, [base, rec], recommended=[rec])
        if carts:
            await in_cart(adb, s, rec)
    body = await get(api)
    mine = [p["recommended_product_id"] for p in body["pairings"] if p["base_product_id"] == str(base.id)]
    assert mine == [str(r2.id), str(r1.id)]  # one add beats two tries with none


async def test_limit_caps_each_ranking(api, adb):
    ps = [await make_product(adb) for _ in range(3)]
    s = await session(adb)
    await job(adb, s, ps)
    body = await get(api, limit=2)
    assert len(body["products"]) <= 2 and len(body["pairings"]) <= 2


async def test_a_deleted_product_is_still_counted(api, adb):
    a = await make_product(adb)
    s = await session(adb)
    await job(adb, s, [a])
    await adb.delete(a)
    await adb.flush()
    body = await get(api)
    gone = next(p for p in body["products"] if p["product_id"] == str(a.id))
    assert (gone["name"], gone["category"], gone["tryons"]) == ("Deleted product", None, 1)
