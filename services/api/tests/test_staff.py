import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import redis
from sqlalchemy import update

from app.api.ws import STAFF_CHANNEL
from app.core.config import settings
from app.models import StaffRequest
from app.services import notifier as notifier_module
from tests.helpers import ADMIN_HEADERS, make_product, make_session

STAFF = {"X-Staff-Key": settings.staff_api_key}


def ask(api, sid, product, size="M", **extra):
    return api.post(
        "/requests", json={"session_id": sid, "product_id": str(product.id), "size": size, **extra}
    )


@pytest.fixture
def staff_events():
    """Everything published on the staff channel while a test runs."""
    conn = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        conn.ping()
    except redis.RedisError:
        pytest.skip("Redis not reachable")
    pubsub = conn.pubsub()
    pubsub.subscribe(STAFF_CHANNEL)
    pubsub.get_message(timeout=1)  # the subscribe confirmation

    def drain() -> list[dict]:
        out = []
        while (m := pubsub.get_message(timeout=0.3)) is not None:
            if m["type"] == "message":
                out.append(json.loads(m["data"]))
        return out

    yield drain
    pubsub.close()
    conn.close()


# --- creating -----------------------------------------------------------------------------------


async def test_a_shopper_can_ask_for_an_item_in_a_size(api, adb, staff_events):
    p = await make_product(adb, name="Silk Blouse", sizes=["S", "M"])
    sid = await make_session(api)

    r = await ask(api, sid, p, "M", color="Ivory")

    assert r.status_code == 201
    body = r.json()
    assert (body["product_name"], body["size"], body["color"], body["status"]) == (
        "Silk Blouse",
        "M",
        "Ivory",
        "open",
    )
    assert body["session_id"] == sid and body["product_id"] == str(p.id)
    assert datetime.fromisoformat(body["created_at"]) <= datetime.now(UTC)
    events = staff_events()
    assert [e["type"] for e in events] == ["request.created"]
    assert events[0]["request"]["id"] == body["id"] and events[0]["request"]["product_name"] == "Silk Blouse"


async def test_asking_twice_for_the_same_open_item_does_not_make_a_second_request(api, adb, staff_events):
    p = await make_product(adb, sizes=["S", "M"])
    sid = await make_session(api)
    first = await ask(api, sid, p, "M")
    again = await ask(api, sid, p, "M")
    other_size = await ask(api, sid, p, "S")

    assert (first.status_code, again.status_code, other_size.status_code) == (201, 200, 201)
    assert again.json()["id"] == first.json()["id"] and other_size.json()["id"] != first.json()["id"]
    assert [e["type"] for e in staff_events()] == [
        "request.created",
        "request.created",
    ]  # no event for the repeat


async def test_a_new_request_is_allowed_once_the_old_one_is_done(api, adb):
    p = await make_product(adb, sizes=["M"])
    sid = await make_session(api)
    first = (await ask(api, sid, p, "M")).json()
    await api.patch(f"/requests/{first['id']}", json={"status": "done"}, headers=STAFF)

    again = await ask(api, sid, p, "M")

    assert again.status_code == 201 and again.json()["id"] != first["id"]


async def test_requests_are_validated(api, adb):
    p = await make_product(adb, sizes=["S", "M"])
    one_size = await make_product(adb, sizes=[])
    sid = await make_session(api)

    assert (await ask(api, str(uuid.uuid4()), p)).status_code == 404  # no such session
    assert (
        await api.post("/requests", json={"session_id": sid, "product_id": str(uuid.uuid4()), "size": "M"})
    ).status_code == 404
    no_size = await api.post("/requests", json={"session_id": sid, "product_id": str(p.id)})
    assert no_size.status_code == 422 and "Choose a size" in no_size.json()["detail"]
    assert (await ask(api, sid, p, "XXL")).status_code == 422
    assert (
        await api.post("/requests", json={"session_id": sid, "product_id": str(one_size.id)})
    ).status_code == 201
    assert (await ask(api, sid, p, "M" * 21)).status_code == 422
    assert (await api.post("/requests", json={})).status_code == 422


# --- staff list and updates ---------------------------------------------------------------------


async def test_staff_need_a_key_to_see_or_change_requests(api, adb):
    p = await make_product(adb, sizes=["M"])
    sid = await make_session(api)
    req = (await ask(api, sid, p, "M")).json()

    assert (await api.get("/requests")).status_code == 401
    assert (await api.get("/requests", headers={"X-Staff-Key": "nope"})).status_code == 401
    assert (await api.patch(f"/requests/{req['id']}", json={"status": "done"})).status_code == 401
    assert (await api.get("/requests", headers=ADMIN_HEADERS)).status_code == 200  # an admin may too
    shown = (await api.get("/requests", headers=STAFF)).json()
    assert req["id"] in [r["id"] for r in shown]


async def test_the_list_shows_open_and_bringing_oldest_first_and_hides_done(api, adb):
    p = await make_product(adb, sizes=["S", "M", "L"])
    sid = await make_session(api)
    a = (await ask(api, sid, p, "S")).json()
    b = (await ask(api, sid, p, "M")).json()
    c = (await ask(api, sid, p, "L")).json()
    # Tests share one transaction, so every row got the same now(); space them out as real requests would be.
    base = datetime.now(UTC)
    for n, req in enumerate((a, b, c)):
        await adb.execute(
            update(StaffRequest)
            .where(StaffRequest.id == uuid.UUID(req["id"]))
            .values(created_at=base + timedelta(minutes=n))
        )
    await api.patch(f"/requests/{b['id']}", json={"status": "bringing"}, headers=STAFF)
    await api.patch(f"/requests/{c['id']}", json={"status": "done"}, headers=STAFF)

    mine = [r for r in (await api.get("/requests", headers=STAFF)).json() if r["session_id"] == sid]
    assert [(r["id"], r["status"]) for r in mine] == [(a["id"], "open"), (b["id"], "bringing")]
    done = (await api.get("/requests", params={"status": "done"}, headers=STAFF)).json()
    assert c["id"] in [r["id"] for r in done]
    assert (await api.get("/requests", params={"status": "bogus"}, headers=STAFF)).status_code == 422


async def test_bringing_then_done_updates_the_request_and_tells_staff(api, adb, staff_events):
    p = await make_product(adb, sizes=["M"])
    sid = await make_session(api)
    req = (await ask(api, sid, p, "M")).json()
    staff_events()  # discard the creation event

    bringing = await api.patch(f"/requests/{req['id']}", json={"status": "bringing"}, headers=STAFF)
    done = await api.patch(f"/requests/{req['id']}", json={"status": "done"}, headers=STAFF)

    assert (bringing.json()["status"], done.json()["status"]) == ("bringing", "done")
    events = staff_events()
    assert [(e["type"], e["request"]["status"]) for e in events] == [
        ("request.updated", "bringing"),
        ("request.updated", "done"),
    ]


async def test_a_request_can_go_straight_to_done_and_repeats_are_harmless(api, adb, staff_events):
    p = await make_product(adb, sizes=["M"])
    sid = await make_session(api)
    req = (await ask(api, sid, p, "M")).json()
    staff_events()

    first = await api.patch(f"/requests/{req['id']}", json={"status": "done"}, headers=STAFF)
    again = await api.patch(f"/requests/{req['id']}", json={"status": "done"}, headers=STAFF)

    assert first.status_code == again.status_code == 200 and again.json() == first.json()
    assert len(staff_events()) == 1  # the repeat announces nothing


async def test_a_done_request_cannot_be_reopened(api, adb):
    p = await make_product(adb, sizes=["M"])
    sid = await make_session(api)
    req = (await ask(api, sid, p, "M")).json()
    await api.patch(f"/requests/{req['id']}", json={"status": "done"}, headers=STAFF)

    r = await api.patch(f"/requests/{req['id']}", json={"status": "bringing"}, headers=STAFF)

    assert r.status_code == 409 and r.json()["detail"] == "This request is already done"


async def test_only_bringing_or_done_can_be_set_and_ids_are_checked(api, adb):
    p = await make_product(adb, sizes=["M"])
    sid = await make_session(api)
    req = (await ask(api, sid, p, "M")).json()
    for bad in ("open", "cancelled", "", None):
        assert (
            await api.patch(f"/requests/{req['id']}", json={"status": bad}, headers=STAFF)
        ).status_code == 422
    assert (
        await api.patch(f"/requests/{uuid.uuid4()}", json={"status": "done"}, headers=STAFF)
    ).status_code == 404
    assert (await api.patch("/requests/nope", json={"status": "done"}, headers=STAFF)).status_code == 422


async def test_a_request_survives_the_product_being_deleted(api, adb):
    p = await make_product(adb, name="Short Lived", sizes=["M"])
    sid = await make_session(api)
    req = (await ask(api, sid, p, "M")).json()
    assert (await api.delete(f"/products/{p.id}", headers=ADMIN_HEADERS)).status_code == 204

    shown = {r["id"]: r for r in (await api.get("/requests", headers=STAFF)).json()}
    assert shown[req["id"]]["product_name"] == "Short Lived"


# --- notifications ------------------------------------------------------------------------------


async def test_a_new_request_is_announced_through_the_notifier(api, adb, monkeypatch, caplog):
    seen = []

    class Recorder:
        async def notify(self, request):
            seen.append((request.product_name, request.size))

    monkeypatch.setitem(notifier_module.NOTIFIERS, "console", Recorder)
    p = await make_product(adb, name="Notified Shirt", sizes=["M"])
    sid = await make_session(api)

    await ask(api, sid, p, "M")
    await ask(api, sid, p, "M")  # a repeat does not notify again

    assert seen == [("Notified Shirt", "M")]


async def test_a_failing_notifier_never_fails_the_shoppers_request(api, adb, monkeypatch, caplog):
    class Broken:
        async def notify(self, request):
            raise RuntimeError("whatsapp is down")

    monkeypatch.setitem(notifier_module.NOTIFIERS, "console", Broken)
    p = await make_product(adb, sizes=["M"])
    sid = await make_session(api)

    with caplog.at_level(logging.ERROR, logger="app.staff"):
        r = await ask(api, sid, p, "M")

    assert r.status_code == 201
    assert any(rec.message == "staff_notify_failed" for rec in caplog.records)


class Req:
    id = uuid.uuid4()
    product_name = "Silk Blouse"
    size = "M"
    color = "Ivory"
    created_at = datetime(2026, 1, 1, 14, 30, tzinfo=UTC)


async def test_the_console_notifier_logs_what_was_asked_for(caplog):
    with caplog.at_level(logging.INFO, logger="app.notifier"):
        await notifier_module.ConsoleNotifier().notify(Req())
    record = next(r for r in caplog.records if r.message == "staff_notification")
    assert record.text == "Outfit requested: Silk Blouse (size M, Ivory)"


def whatsapp(monkeypatch, handler, **overrides):
    values = {
        "whatsapp_token": "tok",
        "whatsapp_phone_number_id": "12345",
        "whatsapp_to": "923001234567, 923009876543",
        "whatsapp_template_name": "",
        "whatsapp_api_base_url": "https://graph.example.test",
        "whatsapp_api_version": "v20.0",
        **overrides,
    }
    for k, v in values.items():
        monkeypatch.setattr(settings, k, v)
    return notifier_module.WhatsAppCloudNotifier(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


async def test_whatsapp_sends_a_text_message_to_every_number(monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((str(request.url), request.headers["authorization"], json.loads(request.content)))
        return httpx.Response(200, json={"messages": [{"id": "wamid"}]})

    await whatsapp(monkeypatch, handler).notify(Req())

    assert [c[0] for c in calls] == ["https://graph.example.test/v20.0/12345/messages"] * 2
    assert {c[1] for c in calls} == {"Bearer tok"}
    assert [c[2]["to"] for c in calls] == ["923001234567", "923009876543"]
    assert calls[0][2] == {
        "messaging_product": "whatsapp",
        "to": "923001234567",
        "type": "text",
        "text": {"body": "Outfit requested at the mirror: Silk Blouse (size M, Ivory)"},
    }


async def test_whatsapp_can_send_an_approved_template_instead(monkeypatch):
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={})

    await whatsapp(
        monkeypatch, handler, whatsapp_template_name="outfit_request", whatsapp_to="923001234567"
    ).notify(Req())

    (payload,) = calls
    assert payload["type"] == "template" and payload["template"]["name"] == "outfit_request"
    assert payload["template"]["language"] == {"code": "en"}
    params = [p["text"] for p in payload["template"]["components"][0]["parameters"]]
    assert params == ["Silk Blouse", "M", "Ivory", "14:30"]


async def test_one_failing_number_does_not_stop_the_others(monkeypatch, caplog):
    sent = []

    def handler(request):
        body = json.loads(request.content)
        sent.append(body["to"])
        return (
            httpx.Response(400, json={"error": "bad number"})
            if body["to"] == "923001234567"
            else httpx.Response(200, json={})
        )

    with caplog.at_level(logging.ERROR, logger="app.notifier"):
        await whatsapp(monkeypatch, handler).notify(Req())

    assert sent == ["923001234567", "923009876543"]
    assert any(r.message == "whatsapp_send_failed" for r in caplog.records)


async def test_a_network_error_is_logged_not_raised(monkeypatch, caplog):
    def handler(request):
        raise httpx.ConnectError("no route")

    with caplog.at_level(logging.ERROR, logger="app.notifier"):
        await whatsapp(monkeypatch, handler).notify(Req())  # must not raise

    assert any(r.message == "whatsapp_send_error" for r in caplog.records)


async def test_an_unconfigured_whatsapp_notifier_says_so_and_sends_nothing(monkeypatch, caplog):
    sent = []

    def handler(request):
        sent.append(1)
        return httpx.Response(200)

    with caplog.at_level(logging.ERROR, logger="app.notifier"):
        await whatsapp(monkeypatch, handler, whatsapp_token="").notify(Req())

    assert sent == [] and any(r.message == "whatsapp_not_configured" for r in caplog.records)


def test_the_notifier_is_chosen_by_setting(monkeypatch):
    assert isinstance(notifier_module.get_notifier(), notifier_module.ConsoleNotifier)
    monkeypatch.setattr(settings, "notifier", "whatsapp")
    assert isinstance(notifier_module.get_notifier(), notifier_module.WhatsAppCloudNotifier)
    assert asyncio.iscoroutinefunction(notifier_module.ConsoleNotifier().notify)
