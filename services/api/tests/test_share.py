import re
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select

from app.api import share as share_module
from app.core.config import settings
from app.models import JobStatus, Order, OrderStatus, PaymentStatus, ShareLink, TryOnJob
from app.services import payments
from tests.helpers import make_product, make_session

CODE = re.compile(f"^[{share_module.CODE_ALPHABET}]{{8}}$")


async def make_job(adb, session_id, product, status=JobStatus.done) -> TryOnJob:
    job = TryOnJob(
        session_id=uuid.UUID(session_id),
        product_ids=[product.id],
        person_image_key="captures/x.webp",
        status=status,
    )
    adb.add(job)
    await adb.flush()
    return job


def add(api, sid, product, **extra):
    return api.post("/cart/add", json={"session_id": sid, "product_id": str(product.id), **extra})


async def stock_of(adb, p) -> int:
    await adb.refresh(p)
    return p.stock


# --- POST /share --------------------------------------------------------------------------------


async def test_a_share_code_is_made_for_a_session(api, adb):
    sid = await make_session(api)

    r = await api.post("/share", json={"session_id": sid})

    assert r.status_code == 201
    body = r.json()
    assert CODE.match(body["short_code"]) and body["path"] == f"/m/{body['short_code']}"
    expires = datetime.fromisoformat(body["expires_at"])
    assert timedelta(hours=23) < expires - datetime.now(UTC) <= timedelta(hours=24)


async def test_asking_again_for_the_same_look_returns_the_same_code(api, adb):
    p = await make_product(adb)
    sid = await make_session(api)
    job = await make_job(adb, sid, p)
    first = await api.post("/share", json={"session_id": sid, "job_id": str(job.id)})
    again = await api.post("/share", json={"session_id": sid, "job_id": str(job.id)})
    other = await api.post("/share", json={"session_id": sid})  # a different look (none): its own code

    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json()["short_code"] == first.json()["short_code"]
    assert other.json()["short_code"] != first.json()["short_code"]


async def test_an_expired_code_is_not_reused(api, adb):
    sid = await make_session(api)
    old = (await api.post("/share", json={"session_id": sid})).json()
    link = await adb.scalar(select(ShareLink).where(ShareLink.short_code == old["short_code"]))
    link.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await adb.flush()

    new = await api.post("/share", json={"session_id": sid})

    assert new.status_code == 201 and new.json()["short_code"] != old["short_code"]


async def test_share_checks_the_session_and_the_look(api, adb):
    p = await make_product(adb)
    mine, theirs = await make_session(api), await make_session(api)
    their_job = await make_job(adb, theirs, p)
    unfinished = await make_job(adb, mine, p, status=JobStatus.processing)

    assert (await api.post("/share", json={"session_id": str(uuid.uuid4())})).status_code == 404
    assert (
        await api.post("/share", json={"session_id": mine, "job_id": str(their_job.id)})
    ).status_code == 404
    assert (
        await api.post("/share", json={"session_id": mine, "job_id": str(uuid.uuid4())})
    ).status_code == 404
    assert (
        await api.post("/share", json={"session_id": mine, "job_id": str(unfinished.id)})
    ).status_code == 409
    assert (await api.post("/share", json={"session_id": "nope"})).status_code == 422


# --- GET /m/{code} ------------------------------------------------------------------------------


async def test_the_mobile_page_shows_the_cart_without_internal_ids(api, adb):
    p = await make_product(adb, name="Linen Shirt", price_pkr=2000, sale_price_pkr=1500, sizes=["M"])
    sid = await make_session(api)
    code = (await api.post("/share", json={"session_id": sid})).json()["short_code"]
    await add(api, sid, p, quantity=2)  # added after the code was made: the page is live

    r = await api.get(f"/m/{code}")

    assert r.status_code == 200
    body = r.json()
    assert body["short_code"] == code and body["order"] is None and body["look_image_url"] is None
    assert body["cart"]["item_count"] == 2 and body["cart"]["subtotal_pkr"] == 3000
    assert body["cart"]["items"][0]["product"]["name"] == "Linen Shirt"
    assert sid not in r.text  # the session id is not exposed through the code


async def test_the_code_is_case_and_space_insensitive(api, adb):
    sid = await make_session(api)
    code = (await api.post("/share", json={"session_id": sid})).json()["short_code"]
    assert (await api.get(f"/m/{code.lower()}")).status_code == 200
    assert (await api.get(f"/m/%20{code}%20")).status_code == 200


async def test_unknown_and_expired_codes(api, adb):
    assert (await api.get("/m/ZZZZZZZZ")).status_code == 404
    sid = await make_session(api)
    code = (await api.post("/share", json={"session_id": sid})).json()["short_code"]
    link = await adb.scalar(select(ShareLink).where(ShareLink.short_code == code))
    link.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await adb.flush()

    gone = await api.get(f"/m/{code}")
    assert gone.status_code == 410 and "expired" in gone.json()["detail"]
    assert (await api.post(f"/m/{code}/checkout", json={})).status_code == 410


async def test_the_look_image_is_a_fresh_signed_url_to_the_stored_result(api, adb, s3):
    p = await make_product(adb)
    sid = await make_session(api)
    job = await make_job(adb, sid, p)
    s3.put_object(Bucket=settings.s3_bucket, Key=f"results/{sid}/{job.id}.webp", Body=b"look-bytes")
    code = (await api.post("/share", json={"session_id": sid, "job_id": str(job.id)})).json()["short_code"]

    body = (await api.get(f"/m/{code}")).json()

    assert body["look_image_url"] and "X-Amz-Signature" in body["look_image_url"]
    async with httpx.AsyncClient() as raw:
        assert (await raw.get(body["look_image_url"])).content == b"look-bytes"


async def test_a_look_whose_image_is_missing_just_has_no_image(api, adb, s3):
    p = await make_product(adb)
    sid = await make_session(api)
    job = await make_job(adb, sid, p)  # nothing was stored for it
    code = (await api.post("/share", json={"session_id": sid, "job_id": str(job.id)})).json()["short_code"]

    r = await api.get(f"/m/{code}")

    assert r.status_code == 200 and r.json()["look_image_url"] is None


# --- POST /m/{code}/checkout --------------------------------------------------------------------


async def start(api, adb, quantity=2, **product):
    p = await make_product(adb, sizes=["M"], stock=5, price_pkr=1000, **product)
    sid = await make_session(api)
    await add(api, sid, p, quantity=quantity)
    code = (await api.post("/share", json={"session_id": sid})).json()["short_code"]
    return p, sid, code


async def test_paying_on_the_phone_places_a_paid_order(api, adb):
    p, sid, code = await start(api, adb)

    r = await api.post(f"/m/{code}/checkout", json={"idempotency_key": str(uuid.uuid4())})

    assert r.status_code == 200
    body = r.json()
    assert body["order"]["subtotal_pkr"] == 2000 and body["order"]["item_count"] == 2
    assert body["payment"] == {
        "provider": "stub",
        "status": "paid",
        "reference": body["payment"]["reference"],
        "redirect_url": None,
    }
    assert body["payment"]["reference"].startswith("stub_")
    assert await stock_of(adb, p) == 3
    page = (await api.get(f"/m/{code}")).json()
    assert page["cart"]["items"] == [] and page["order"]["pickup_code"] == body["order"]["pickup_code"]
    row = await adb.scalar(select(Order).where(Order.session_id == uuid.UUID(sid)))
    await adb.refresh(row)
    assert (row.payment_status, row.payment_provider) == (PaymentStatus.paid, "stub")


async def test_a_retry_is_not_charged_twice(api, adb, monkeypatch):
    p, sid, code = await start(api, adb)
    charges = []
    real = payments.StubPaymentProvider.charge

    async def counting(self, **kw):
        charges.append(kw["order_id"])
        return await real(self, **kw)

    monkeypatch.setattr(payments.StubPaymentProvider, "charge", counting)
    key = str(uuid.uuid4())

    first = await api.post(f"/m/{code}/checkout", json={"idempotency_key": key})
    again = await api.post(f"/m/{code}/checkout", json={"idempotency_key": key})

    assert first.status_code == again.status_code == 200
    assert again.json()["order"]["id"] == first.json()["order"]["id"]
    assert again.json()["payment"]["status"] == "paid"
    assert again.json()["payment"]["reference"] == first.json()["payment"]["reference"]
    assert len(charges) == 1 and await stock_of(adb, p) == 3


async def test_a_declined_payment_cancels_the_order_and_puts_the_cart_back(api, adb, monkeypatch):
    monkeypatch.setattr(settings, "stub_payment_outcome", "failed")
    p, sid, code = await start(api, adb, quantity=3)

    r = await api.post(f"/m/{code}/checkout", json={})

    assert r.status_code == 402 and r.json()["detail"] == "The payment was declined"
    assert await stock_of(adb, p) == 5  # nothing was kept
    cart = (await api.get(f"/cart/{sid}")).json()
    assert cart["item_count"] == 3 and cart["items"][0]["size"] == "M"  # the shopper can try again
    row = await adb.scalar(select(Order).where(Order.session_id == uuid.UUID(sid)))
    await adb.refresh(row)
    assert (row.status, row.payment_status) == (OrderStatus.cancelled, PaymentStatus.failed)
    page = (await api.get(f"/m/{code}")).json()
    assert page["order"] is None  # a failed attempt is not shown as an order

    monkeypatch.setattr(settings, "stub_payment_outcome", "paid")  # and trying again works
    again = await api.post(f"/m/{code}/checkout", json={})
    assert again.status_code == 200 and again.json()["order"]["item_count"] == 3
    assert await stock_of(adb, p) == 2


async def test_an_empty_cart_or_short_stock_is_refused_without_charging(api, adb, monkeypatch):
    charges = []

    async def never(self, **kw):
        charges.append(kw)
        raise AssertionError("must not charge")

    monkeypatch.setattr(payments.StubPaymentProvider, "charge", never)
    sid = await make_session(api)
    code = (await api.post("/share", json={"session_id": sid})).json()["short_code"]
    assert (await api.post(f"/m/{code}/checkout", json={})).status_code == 409  # empty

    p, sid2, code2 = await start(api, adb, quantity=2)
    p.stock = 1
    await adb.flush()
    r = await api.post(f"/m/{code2}/checkout", json={})
    assert r.status_code == 409 and "only 1 left" in r.json()["detail"]
    assert charges == []


async def test_the_kiosk_counter_checkout_is_still_unpaid(api, adb):
    p = await make_product(adb, sizes=["M"])
    sid = await make_session(api)
    await add(api, sid, p)

    r = await api.post("/checkout", json={"session_id": sid})

    assert r.status_code == 201
    row = await adb.scalar(select(Order).where(Order.session_id == uuid.UUID(sid)))
    await adb.refresh(row)
    assert (row.payment_status, row.payment_provider) == (PaymentStatus.unpaid, None)


def test_the_provider_registry(monkeypatch):
    assert payments.get_payment_provider().name == "stub"
    monkeypatch.setattr(settings, "payment_provider", "nope")
    try:
        payments.get_payment_provider()
    except RuntimeError as e:
        assert "nope" in str(e) and "stub" in str(e)
    else:
        raise AssertionError("an unknown provider must fail loudly")
