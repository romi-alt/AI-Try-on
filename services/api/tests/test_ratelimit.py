"""Rate limiting: per session where a request has one, per address where it does not."""

import asyncio
import hashlib
import json
import uuid

import httpx
import pytest
from fastapi import HTTPException
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

from app.core import ratelimit
from app.core.config import settings
from app.core.ratelimit import RULES, Rule
from app.core.redis import get_redis
from app.main import app
from tests.helpers import ADMIN_HEADERS, make_product, make_session

KIOSK = "http://localhost:3000"


def tighten(monkeypatch, **limits):
    """Replace rules with `limit` hits per 60 s, e.g. tighten(monkeypatch, cart_session=2)."""
    for name, limit in limits.items():
        monkeypatch.setitem(RULES, name, Rule(limit, 60))


def client_from(ip: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=(ip, 5000)), base_url="http://test"
    )


# --- the counter itself --------------------------------------------------------------------------


async def test_the_limit_is_enforced_then_answers_429_with_retry_after(monkeypatch):
    tighten(monkeypatch, cart_session=3)
    for _ in range(3):
        await ratelimit.check("cart_session", "s1")
    with pytest.raises(HTTPException) as e:
        await ratelimit.check("cart_session", "s1")
    assert e.value.status_code == 429
    assert 1 <= int(e.value.headers["Retry-After"]) <= 60
    assert "wait" in e.value.detail


async def test_keys_are_counted_separately(monkeypatch):
    tighten(monkeypatch, cart_session=1)
    await ratelimit.check("cart_session", "a")
    await ratelimit.check("cart_session", "b")  # another session: fresh allowance
    with pytest.raises(HTTPException):
        await ratelimit.check("cart_session", "a")


async def test_the_window_resets(monkeypatch):
    monkeypatch.setitem(RULES, "cart_session", Rule(1, 1))
    await ratelimit.check("cart_session", "x")
    with pytest.raises(HTTPException):
        await ratelimit.check("cart_session", "x")
    await asyncio.sleep(1.2)
    await ratelimit.check("cart_session", "x")


async def test_a_counter_without_an_expiry_still_expires(monkeypatch):
    """A crash between INCR and EXPIRE must not leave a key that blocks someone forever."""
    monkeypatch.setitem(RULES, "cart_session", Rule(1, 30))
    key = f"{settings.rate_limit_prefix}:cart_session:orphan"
    get_redis().set(key, 5)  # no TTL
    with pytest.raises(HTTPException):
        await ratelimit.check("cart_session", "orphan")
    assert 0 < get_redis().ttl(key) <= 30


async def test_the_scale_setting_multiplies_every_limit(monkeypatch):
    tighten(monkeypatch, cart_session=2)
    monkeypatch.setattr(settings, "rate_limit_scale", 2.0)
    for _ in range(4):
        await ratelimit.check("cart_session", "s")
    with pytest.raises(HTTPException):
        await ratelimit.check("cart_session", "s")


async def test_it_can_be_turned_off(monkeypatch):
    tighten(monkeypatch, cart_session=1)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    for _ in range(5):
        await ratelimit.check("cart_session", "s")


async def test_addresses_are_hashed_in_redis(monkeypatch):
    await ratelimit.check("session_start_ip", "203.0.113.77", ip=True)
    keys = get_redis().keys(f"{settings.rate_limit_prefix}:*")
    assert keys and all("203.0.113.77" not in k for k in keys)
    assert hashlib.sha256(b"203.0.113.77").hexdigest()[:16] in keys[0]


class BrokenRedis:
    def register_script(self, *_):
        raise ConnectionError("redis is down")

    def get(self, *_):
        raise ConnectionError("redis is down")


async def test_redis_trouble_lets_requests_through_by_default(monkeypatch):
    monkeypatch.setattr(ratelimit, "get_redis", lambda: BrokenRedis())
    await ratelimit.check("cart_session", "s")  # no exception
    assert ratelimit.peek_blocked("bad_key_ip", "1.2.3.4") == 0


async def test_it_can_be_made_to_fail_closed(monkeypatch):
    monkeypatch.setattr(ratelimit, "get_redis", lambda: BrokenRedis())
    monkeypatch.setattr(settings, "rate_limit_fail_open", False)
    with pytest.raises(HTTPException) as e:
        await ratelimit.check("cart_session", "s")
    assert e.value.status_code == 503


# --- each route is limited, and by the right key -------------------------------------------------

NOBODY = str(uuid.UUID(int=0))  # a session that does not exist: the limit is checked before the lookup


SESSION_CALLS = [
    ("cart_session", lambda c, s: c.post("/cart/add", json={"session_id": s, "product_id": NOBODY})),
    (
        "tryon_session",
        lambda c, s: c.post("/tryon", json={"session_id": s, "capture_key": "x", "product_ids": [NOBODY]}),
    ),
    ("share_session", lambda c, s: c.post("/share", json={"session_id": s})),
    (
        "request_outfit_session",
        lambda c, s: c.post("/requests", json={"session_id": s, "product_id": NOBODY}),
    ),
    ("checkout_session", lambda c, s: c.post("/checkout", json={"session_id": s})),
    (
        "capture_session",
        lambda c, s: c.post(
            "/capture", data={"session_id": s}, files={"file": ("a.jpg", b"x", "image/jpeg")}
        ),
    ),
]


@pytest.mark.parametrize(("rule", "call"), SESSION_CALLS, ids=[r for r, _ in SESSION_CALLS])
async def test_session_routes_answer_429_after_the_limit_and_count_each_session_separately(
    api, monkeypatch, rule, call
):
    tighten(monkeypatch, **{rule: 2})
    mine, someone_else = str(uuid.uuid4()), str(uuid.uuid4())
    first, second, third = [await call(api, mine) for _ in range(3)]
    assert first.status_code != 429 and second.status_code != 429
    assert third.status_code == 429
    assert int(third.headers["retry-after"]) >= 1 and "Too many" in third.json()["detail"]
    assert (await call(api, someone_else)).status_code != 429  # a different session has its own allowance


async def test_cart_edits_share_the_cart_limit(api, monkeypatch):
    tighten(monkeypatch, cart_session=2)
    item = str(uuid.uuid4())
    assert (await api.patch(f"/cart/{NOBODY}/items/{item}", json={"quantity": 2})).status_code != 429
    assert (await api.delete(f"/cart/{NOBODY}/items/{item}")).status_code != 429
    assert (await api.patch(f"/cart/{NOBODY}/items/{item}", json={"quantity": 2})).status_code == 429


async def test_one_shopper_cannot_use_up_anothers_allowance(api, monkeypatch):
    tighten(monkeypatch, cart_session=1)
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    body = lambda s: {"session_id": s, "product_id": NOBODY}  # noqa: E731
    assert (await api.post("/cart/add", json=body(a))).status_code != 429
    assert (await api.post("/cart/add", json=body(a))).status_code == 429
    assert (await api.post("/cart/add", json=body(b))).status_code != 429


async def test_a_real_cart_flow_still_works_under_the_default_limits(api, adb):
    product = await make_product(adb)
    sid = await make_session(api)
    for _ in range(5):
        r = await api.post(
            "/cart/add",
            json={"session_id": sid, "product_id": str(product.id), "size": "S", "color": "Ivory"},
        )
        assert r.status_code == 200, r.text


async def test_session_creation_is_limited_per_address(api, monkeypatch):
    tighten(monkeypatch, session_start_ip=2)
    body = {"consent_given": True}
    async with client_from("198.51.100.1") as a, client_from("198.51.100.2") as b:
        assert [(await a.post("/sessions", json=body)).status_code for _ in range(3)] == [201, 201, 429]
        assert (await b.post("/sessions", json=body)).status_code == 201  # another address is unaffected


async def test_the_mobile_page_is_limited_per_address(api, monkeypatch):
    tighten(monkeypatch, mobile_page_ip=2)
    async with client_from("198.51.100.9") as c:
        codes = [(await c.get("/m/ABCD2345")).status_code for _ in range(3)]
    assert codes[:2] == [404, 404] and codes[2] == 429


async def test_guessing_mobile_codes_locks_the_address_out_even_for_a_valid_code(api, adb, monkeypatch):
    tighten(monkeypatch, mobile_bad_code_ip=3)
    sid = await make_session(api)
    good = (await api.post("/share", json={"session_id": sid})).json()["short_code"]
    async with client_from("198.51.100.20") as guesser, client_from("198.51.100.21") as other:
        for _ in range(3):
            assert (await guesser.get("/m/ZZZZZZZZ")).status_code == 404
        locked = await guesser.get(f"/m/{good}")
        assert locked.status_code == 429 and "Retry-After" in locked.headers
        assert (await other.get(f"/m/{good}")).status_code == 200  # nobody else is affected


@pytest.mark.parametrize("code", ["", "AB", "A" * 40, "ABC$1234", "AB CD EFG", "../../etc"])
async def test_codes_that_cannot_exist_are_refused_before_any_lookup(api, code):
    r = await api.get(f"/m/{code}")
    assert r.status_code in (404, 422)
    r2 = await api.post(f"/m/{code}/checkout", json={})
    assert r2.status_code in (404, 405, 422)


async def test_mobile_checkout_is_limited_per_code(api, monkeypatch):
    tighten(monkeypatch, mobile_checkout_code=2)
    sid = await make_session(api)
    code = (await api.post("/share", json={"session_id": sid})).json()["short_code"]
    statuses = [(await api.post(f"/m/{code}/checkout", json={})).status_code for _ in range(3)]
    assert statuses[:2] == [409, 409] and statuses[2] == 429  # an empty cart is 409; the third is refused


# --- wrong admin and staff keys ------------------------------------------------------------------


async def test_wrong_admin_keys_lock_the_address_out_even_for_the_right_key(monkeypatch):
    tighten(monkeypatch, bad_key_ip=3)
    async with client_from("198.51.100.30") as attacker, client_from("198.51.100.31") as admin:
        for _ in range(3):
            assert (await attacker.get("/admin/stats", headers={"X-Admin-Key": "nope"})).status_code == 401
        locked = await attacker.get("/admin/stats", headers=ADMIN_HEADERS)
        assert locked.status_code == 429
        assert (await admin.get("/admin/stats", headers=ADMIN_HEADERS)).status_code == 200


async def test_wrong_staff_keys_count_too_and_the_admin_key_is_still_accepted_for_staff(api, monkeypatch):
    tighten(monkeypatch, bad_key_ip=2)
    async with client_from("198.51.100.40") as c:
        assert (await c.get("/requests", headers={"X-Staff-Key": settings.staff_api_key})).status_code == 200
        assert (await c.get("/requests", headers=ADMIN_HEADERS)).status_code == 200
        for _ in range(2):
            assert (await c.get("/requests", headers={"X-Staff-Key": "wrong"})).status_code == 401
        assert (await c.get("/requests", headers={"X-Staff-Key": settings.staff_api_key})).status_code == 429


async def test_correct_keys_never_count_against_the_limit(monkeypatch):
    tighten(monkeypatch, bad_key_ip=1)
    async with client_from("198.51.100.50") as c:
        for _ in range(5):
            assert (await c.get("/admin/stats", headers=ADMIN_HEADERS)).status_code == 200


@pytest.mark.parametrize("path", ["/admin/stats", "/requests"])
async def test_a_non_ascii_key_is_a_401_not_a_crash(api, path):
    r = await api.get(path, headers={"X-Admin-Key": b"caf\xe9", "X-Staff-Key": b"\xff\xfe"})
    assert r.status_code == 401


async def test_an_absurdly_long_key_header_is_a_422(api):
    r = await api.get("/admin/stats", headers={"X-Admin-Key": "k" * 300})
    assert r.status_code == 422


# --- WebSockets ----------------------------------------------------------------------------------


async def test_websocket_connections_are_limited_per_address(live_server, monkeypatch):
    tighten(monkeypatch, ws_connect_ip=2)
    sid = uuid.uuid4()
    for _ in range(2):
        ws = await connect(f"ws://{live_server}/ws?session={sid}", origin=KIOSK)
        await ws.close()
    with pytest.raises(InvalidStatus) as e:  # refused during the handshake; the kiosk backs off and polls
        await connect(f"ws://{live_server}/ws?session={sid}", origin=KIOSK)
    assert e.value.response.status_code == 403


async def test_the_staff_socket_refuses_a_long_auth_message_and_counts_wrong_keys(live_server, monkeypatch):
    tighten(monkeypatch, bad_key_ip=2)

    async def attempt(key: str) -> bool:
        """True if the server said ready."""
        ws = await connect(f"ws://{live_server}/ws/staff", origin=KIOSK)
        try:
            await ws.send(json.dumps({"type": "auth", "key": key}))
            return json.loads(await asyncio.wait_for(ws.recv(), 3)) == {"type": "ready"}
        except Exception:  # the server closed the socket
            return False
        finally:
            await ws.close()

    assert await attempt("x" * 5000) is False  # too long: refused, and counted as a wrong key
    assert await attempt("wrong") is False
    assert await attempt(settings.staff_api_key) is False  # locked out, even with the right key
