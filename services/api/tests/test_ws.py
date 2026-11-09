"""WebSocket /ws against the real app served by uvicorn, with a real Redis and the real websockets client.

Only Redis is needed (the endpoint never touches Postgres); tests skip when it is not reachable.
"""

import asyncio
import json
import time
import uuid

import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosedError, InvalidStatus

from app.core.config import Settings, settings

KIOSK = "http://localhost:3000"
STRANGER = "https://evil.example"
PING = {"type": "ping"}


def new_session() -> str:
    return str(uuid.uuid4())


def url(server: str, session: str | None = None, query: str | None = None) -> str:
    return f"ws://{server}/ws" + (f"?{query}" if query is not None else f"?session={session}")


async def recv(ws, timeout: float = 3.0) -> str:
    return await asyncio.wait_for(ws.recv(), timeout)


async def recv_events(ws, n: int, timeout: float = 3.0) -> list[dict]:
    """The next n job messages, skipping heartbeats."""
    events: list[dict] = []
    deadline = time.monotonic() + timeout
    while len(events) < n:
        message = json.loads(await recv(ws, max(0.05, deadline - time.monotonic())))
        if message != PING:
            events.append(message)
    return events


async def silence(ws, seconds: float = 0.3) -> None:
    """Assert nothing arrives for a short while."""
    with pytest.raises(TimeoutError):
        await recv(ws, seconds)


async def patterns(aredis) -> int:
    return await aredis.pubsub_numpat()


async def settle_to(aredis, expected: int, timeout: float = 3.0) -> int:
    """Wait for the number of pattern subscriptions to reach `expected`; return what it ended at."""
    deadline = time.monotonic() + timeout
    while (n := await patterns(aredis)) != expected and time.monotonic() < deadline:
        await asyncio.sleep(0.05)
    return n


def job_message(job: str, pct: int, status: str = "processing") -> str:
    return json.dumps({"job": job, "status": status, "pct": pct})


# --- forwarding -------------------------------------------------------------------------------------


async def test_every_message_on_the_session_channels_is_forwarded_as_is_and_in_order(live_server, aredis):
    s = new_session()
    async with connect(url(live_server, s)) as ws:
        # Published the instant the connection opens: the subscription must already be live.
        payloads = [job_message("j1", pct) for pct in (0, 10, 20)]
        for p in payloads:
            await aredis.publish(f"session:{s}:job", p)
        await aredis.publish(f"session:{s}:other", "plain text, not json")  # any session:{id}:* channel

        assert [await recv(ws) for _ in range(4)] == [*payloads, "plain text, not json"]


async def test_the_subscription_is_live_before_the_connection_opens(live_server, aredis):
    """No race for a client that connects and immediately starts a job."""
    for _ in range(20):
        s = new_session()
        async with connect(url(live_server, s)) as ws:
            await aredis.publish(f"session:{s}:job", job_message("j", 1))
            assert json.loads(await recv(ws))["pct"] == 1


async def test_only_the_connected_sessions_messages_are_delivered(live_server, aredis):
    mine, theirs = new_session(), new_session()
    async with connect(url(live_server, mine)) as ws:
        await aredis.publish(f"session:{theirs}:job", job_message("not-mine", 50))
        await aredis.publish(f"session:{mine}:job", job_message("mine", 60))
        await aredis.publish(f"other:{mine}:job", "wrong prefix")

        assert json.loads(await recv(ws))["job"] == "mine"
        await silence(ws)


async def test_unicode_and_large_payloads_survive(live_server, aredis):
    s = new_session()
    big = json.dumps(
        {"job": "j", "status": "failed", "pct": 3, "error": "Désolé, réessayez 🙏 " + "x" * 200_000}
    )
    async with connect(url(live_server, s), max_size=None) as ws:
        await aredis.publish(f"session:{s}:job", big)
        assert await recv(ws) == big


async def test_every_connection_for_a_session_receives_every_message(live_server, aredis):
    s = new_session()
    async with (
        connect(url(live_server, s)) as a,
        connect(url(live_server, s)) as b,
        connect(url(live_server, s)) as c,
    ):
        for pct in (1, 2, 3):
            await aredis.publish(f"session:{s}:job", job_message("j", pct))
        for ws in (a, b, c):
            assert [e["pct"] for e in await recv_events(ws, 3)] == [1, 2, 3]


async def test_messages_the_client_sends_are_ignored(live_server, aredis):
    s = new_session()
    async with connect(url(live_server, s)) as ws:
        await ws.send("hello?")
        await ws.send(b"\x00\x01")
        await aredis.publish(f"session:{s}:job", job_message("j", 7))
        assert json.loads(await recv(ws))["pct"] == 7


# --- heartbeat --------------------------------------------------------------------------------------


def test_heartbeat_default_is_25_seconds():
    assert Settings(_env_file=None).ws_heartbeat_seconds == 25.0


async def test_a_ping_is_sent_every_interval(live_server, monkeypatch):
    monkeypatch.setattr(settings, "ws_heartbeat_seconds", 0.2)
    async with connect(url(live_server, new_session())) as ws:
        stamps = []
        for _ in range(4):
            assert json.loads(await recv(ws)) == PING
            stamps.append(time.monotonic())

    gaps = [b - a for a, b in zip(stamps, stamps[1:], strict=False)]
    assert all(0.15 <= g <= 0.45 for g in gaps), gaps


async def test_no_ping_before_the_interval_has_elapsed(live_server, monkeypatch):
    monkeypatch.setattr(settings, "ws_heartbeat_seconds", 5.0)
    async with connect(url(live_server, new_session())) as ws:
        await silence(ws, 0.4)


async def test_heartbeats_and_job_messages_interleave_without_corruption(live_server, aredis, monkeypatch):
    monkeypatch.setattr(settings, "ws_heartbeat_seconds", 0.05)
    s = new_session()
    async with connect(url(live_server, s)) as ws:

        async def publish():
            for pct in range(30):
                await aredis.publish(f"session:{s}:job", job_message("j", pct))
                await asyncio.sleep(0.01)

        publisher = asyncio.create_task(publish())
        seen, pings = [], 0
        while len(seen) < 30:
            message = json.loads(await recv(ws))  # every frame is a whole JSON document
            if message == PING:
                pings += 1
            else:
                seen.append(message["pct"])
        await publisher

    assert seen == list(range(30)) and pings >= 3


# --- clean disconnect -------------------------------------------------------------------------------


async def test_the_redis_subscription_is_removed_on_a_normal_close(live_server, aredis):
    base = await patterns(aredis)
    async with connect(url(live_server, new_session())) as ws:
        assert await settle_to(aredis, base + 1) == base + 1  # the pattern is subscribed while connected
        await ws.ping()
    assert await settle_to(aredis, base) == base


async def test_the_redis_subscription_is_removed_when_the_client_vanishes(live_server, aredis):
    base = await patterns(aredis)
    ws = await connect(url(live_server, new_session()))
    assert await settle_to(aredis, base + 1) == base + 1

    ws.transport.abort()  # no closing handshake: the network just went away

    assert await settle_to(aredis, base) == base


async def test_closing_one_connection_leaves_the_others_working(live_server, aredis):
    s = new_session()
    base = await patterns(aredis)
    keep = await connect(url(live_server, s))
    drop = await connect(url(live_server, s))
    await drop.close()

    await aredis.publish(f"session:{s}:job", job_message("j", 9))
    assert json.loads(await recv(keep))["pct"] == 9
    await keep.close()
    assert await settle_to(aredis, base) == base


async def test_publishing_after_every_client_left_is_harmless(live_server, aredis):
    s = new_session()
    ws = await connect(url(live_server, s))
    ws.transport.abort()
    await asyncio.sleep(0.2)
    assert await aredis.publish(f"session:{s}:job", job_message("j", 1)) == 0  # nobody is listening

    async with connect(url(live_server, s)) as again:  # and the server is still fine
        await aredis.publish(f"session:{s}:job", job_message("j", 2))
        assert json.loads(await recv(again))["pct"] == 2


async def test_many_connect_disconnect_cycles_leak_nothing(live_server, aredis):
    base = await patterns(aredis)
    clients_before = (await aredis.info("clients"))["connected_clients"]
    for _ in range(25):
        async with connect(url(live_server, new_session())):
            pass
    assert await settle_to(aredis, base) == base
    deadline = time.monotonic() + 3
    while (await aredis.info("clients"))[
        "connected_clients"
    ] > clients_before and time.monotonic() < deadline:
        await asyncio.sleep(0.05)
    assert (await aredis.info("clients"))[
        "connected_clients"
    ] <= clients_before  # no leaked Redis connections


# --- refusals ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query", ["session=*", "session=not-a-uuid", "session=", "", "other=1", "session=%2A"]
)
async def test_a_missing_or_malformed_session_is_refused_without_subscribing(live_server, aredis, query):
    base = await patterns(aredis)

    with pytest.raises(InvalidStatus) as refused:
        async with connect(url(live_server, query=query)):
            pass

    assert refused.value.response.status_code == 403
    assert await patterns(aredis) == base


async def test_a_glob_cannot_be_used_to_listen_to_other_sessions(live_server, aredis):
    victim = new_session()
    with pytest.raises(InvalidStatus):
        async with connect(url(live_server, query="session=*")):
            pass
    with pytest.raises(InvalidStatus):
        async with connect(url(live_server, query=f"session={victim[:8]}*")):
            pass
    await aredis.publish(f"session:{victim}:job", job_message("secret", 1))  # nobody could have received it


async def test_the_kiosk_origin_is_allowed(live_server, aredis):
    s = new_session()
    async with connect(url(live_server, s), origin=KIOSK) as ws:
        await aredis.publish(f"session:{s}:job", job_message("j", 1))
        assert json.loads(await recv(ws))["pct"] == 1


async def test_other_origins_are_refused(live_server, aredis):
    base = await patterns(aredis)
    with pytest.raises(InvalidStatus) as refused:
        async with connect(url(live_server, new_session()), origin=STRANGER):
            pass
    assert refused.value.response.status_code == 403
    assert await patterns(aredis) == base


async def test_clients_without_an_origin_header_are_allowed(live_server):
    async with connect(url(live_server, new_session()), origin=None):
        pass


async def test_the_connection_is_refused_when_redis_is_unavailable(live_server, monkeypatch):
    monkeypatch.setattr(settings, "redis_url", "redis://127.0.0.1:1/0")
    with pytest.raises(InvalidStatus):  # the client falls back to polling GET /jobs/{id}
        async with connect(url(live_server, new_session())):
            pass


async def test_losing_the_redis_subscription_closes_the_socket_so_the_client_resyncs(live_server, aredis):
    s = new_session()
    async with connect(url(live_server, s)) as ws:
        await aredis.publish(f"session:{s}:job", job_message("j", 1))
        assert json.loads(await recv(ws))["pct"] == 1

        await aredis.execute_command("CLIENT", "KILL", "TYPE", "pubsub")  # Redis drops the subscriber

        with pytest.raises(ConnectionClosedError) as closed:
            await recv(ws, 5)
    assert closed.value.rcvd.code == 1011  # "internal error": reconnect, then read GET /jobs/{id}
