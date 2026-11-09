"""WebSocket /ws/staff against the real app served by uvicorn, with a real Redis."""

import asyncio
import json

import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosedError

from app.api.ws import STAFF_CHANNEL
from app.core.config import settings

KIOSK = "http://localhost:3000"
STRANGER = "https://evil.example"


async def recv_json(ws, timeout: float = 3.0) -> dict:
    return json.loads(await asyncio.wait_for(ws.recv(), timeout))


async def staff_socket(server, key=None, origin=KIOSK):
    ws = await connect(f"ws://{server}/ws/staff", origin=origin)
    if key is not None:
        await ws.send(json.dumps({"type": "auth", "key": key}))
    return ws


async def test_a_staff_socket_authenticates_then_receives_events_in_order(live_server, aredis):
    ws = await staff_socket(live_server, settings.staff_api_key)
    try:
        assert await recv_json(ws) == {"type": "ready"}
        for n in range(3):
            await aredis.publish(STAFF_CHANNEL, json.dumps({"type": "request.created", "request": {"n": n}}))
        got = [await recv_json(ws) for _ in range(3)]
        assert [g["request"]["n"] for g in got] == [0, 1, 2]
    finally:
        await ws.close()


async def test_the_subscription_is_live_before_ready_is_sent(live_server, aredis):
    ws = await staff_socket(live_server, settings.staff_api_key)
    try:
        await recv_json(ws)  # ready
        await aredis.publish(
            STAFF_CHANNEL, json.dumps({"type": "request.updated", "request": {"n": 1}})
        )  # straight away
        assert (await recv_json(ws))["request"]["n"] == 1
    finally:
        await ws.close()


async def test_the_admin_key_is_accepted_too(live_server):
    ws = await staff_socket(live_server, settings.admin_api_key)
    try:
        assert await recv_json(ws) == {"type": "ready"}
    finally:
        await ws.close()


@pytest.mark.parametrize(
    "first",
    [
        '{"type":"auth","key":"nope"}',
        '{"type":"auth"}',
        '{"type":"hello"}',
        "not json",
        "[]",
        '{"type":"auth","key":5}',
    ],
)
async def test_a_wrong_or_malformed_first_message_is_refused_and_nothing_is_delivered(
    live_server, aredis, first
):
    ws = await connect(f"ws://{live_server}/ws/staff", origin=KIOSK)
    await ws.send(first)
    await aredis.publish(STAFF_CHANNEL, json.dumps({"type": "request.created", "request": {"secret": 1}}))
    with pytest.raises(ConnectionClosedError):
        while True:
            message = await asyncio.wait_for(ws.recv(), 3)
            assert "secret" not in message and "ready" not in message  # nothing leaks before the close


async def test_no_first_message_means_the_socket_is_closed(live_server, monkeypatch):
    monkeypatch.setattr("app.api.ws.STAFF_AUTH_TIMEOUT_SECONDS", 0.3)
    ws = await connect(f"ws://{live_server}/ws/staff", origin=KIOSK)
    with pytest.raises(ConnectionClosedError):
        await asyncio.wait_for(ws.recv(), 3)


async def test_a_stranger_origin_is_refused(live_server):
    with pytest.raises(Exception) as e:
        ws = await staff_socket(live_server, settings.staff_api_key, origin=STRANGER)
        await asyncio.wait_for(ws.recv(), 3)
    assert "1008" in str(e.value) or "policy" in str(e.value).lower() or "403" in str(e.value)


async def test_session_job_messages_do_not_reach_the_staff_channel(live_server, aredis):
    ws = await staff_socket(live_server, settings.staff_api_key)
    try:
        await recv_json(ws)
        await aredis.publish(
            "session:00000000-0000-0000-0000-000000000000:job", json.dumps({"job": "x", "pct": 1})
        )
        with pytest.raises(TimeoutError):
            await recv_json(ws, timeout=0.5)
    finally:
        await ws.close()


async def test_the_staff_subscription_is_removed_when_the_socket_closes(live_server, aredis):
    base = await aredis.execute_command("PUBSUB", "NUMPAT")
    ws = await staff_socket(live_server, settings.staff_api_key)
    await recv_json(ws)
    assert (await aredis.execute_command("PUBSUB", "NUMPAT")) == base + 1
    await ws.close()
    for _ in range(30):
        if (await aredis.execute_command("PUBSUB", "NUMPAT")) == base:
            return
        await asyncio.sleep(0.1)
    raise AssertionError("the pattern subscription leaked")
