"""End to end: a real mock job, from POST /tryon to the WebSocket.

Everything real except the clock: the API served by uvicorn, a real WebSocket client, real Redis (queue,
pub/sub and the job state hash), real Postgres (a private schema), an S3-compatible server, the real RQ queue
and the worker's own job code with the MockProvider. The only stand-in is how the worker is run: in a thread
of this process instead of a separate one, so the test can drive and observe it.

Needs the worker package importable (conftest adds `services/worker` to the path; docker-compose mounts it at
/worker) plus a migrated Postgres, Redis and nothing else; it skips otherwise.
"""

import asyncio
import json
import time
import uuid
from dataclasses import dataclass

import httpx
import pytest
from rq import Queue, SimpleWorker
from rq.serializers import JSONSerializer
from rq.timeouts import TimerDeathPenalty
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool
from websockets.asyncio.client import connect

from app.core.config import settings
from app.core.db import Base, get_async_db
from app.main import app
from app.models import Product, ProductCategory
from tests.helpers import make_image_bytes

PING = {"type": "ping"}


class ThreadWorker(SimpleWorker):
    """RQ's in-process worker, usable off the main thread.

    Signal handlers and RQ's default SIGALRM job timeout only work on the main thread, so they are swapped
    for RQ's timer-based timeout and no handlers.
    """

    death_penalty_class = TimerDeathPenalty

    def _install_signal_handlers(self):
        pass


@dataclass
class Stack:
    http_base: str
    ws_base: str
    sync_engine: object
    queue: Queue

    def ws(self, session: str) -> str:
        return f"{self.ws_base}/ws?session={session}"

    def add_product(self, name: str, category: str = "top") -> str:
        import io

        from PIL import Image

        from app.core.storage import internal_client

        key = f"products/{uuid.uuid4()}.png"
        buf = io.BytesIO()
        Image.new("RGBA", (300, 400), (190, 40, 70, 255)).save(buf, format="PNG")
        internal_client().put_object(
            Bucket=settings.s3_bucket, Key=key, Body=buf.getvalue(), ContentType="image/png"
        )
        with Session(self.sync_engine) as db:
            product = Product(
                name=name,
                category=ProductCategory(category),
                price_pkr=3990,
                sizes=["M"],
                colors=[{"name": "Ivory", "hex": "#efe6d2"}],
                stock=5,
                garment_image_url=f"{settings.s3_public_base_url}/{key}",
            )
            db.add(product)
            db.commit()
            return str(product.id)

    def run_worker(self) -> None:
        """Process everything on the queue, as the worker service would."""
        ThreadWorker([self.queue], connection=self.queue.connection, serializer=JSONSerializer).work(
            burst=True
        )


@pytest.fixture
async def stack(live_server, s3, rq_queue, monkeypatch):
    worker_db = pytest.importorskip(
        "worker.db", reason="worker package not importable (see module docstring)"
    )
    import worker.config
    import worker.storage

    schema = f"it_{uuid.uuid4().hex[:10]}"
    options = {"options": f"-csearch_path={schema},public"}  # public: the pgvector type lives there
    base = create_engine(settings.database_url)
    try:
        with base.connect() as conn:
            migrated = "products" in inspect(conn).get_table_names()
    except OperationalError:
        base.dispose()
        pytest.skip("Postgres not reachable")
    if not migrated:
        base.dispose()
        pytest.skip("database not migrated (run `make migrate`)")
    with base.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    sync_engine = create_engine(settings.database_url, connect_args=options)
    Base.metadata.create_all(sync_engine)
    async_engine = create_async_engine(settings.database_url, poolclass=NullPool, connect_args=options)

    async def db_override():
        async with AsyncSession(async_engine, expire_on_commit=False) as session:
            yield session

    app.dependency_overrides[get_async_db] = db_override

    # The worker half of the stack: same bucket and queue, a fast mock, its own DB access on the schema.
    monkeypatch.setattr(worker_db, "engine", sync_engine)
    for name in (
        "s3_endpoint_url",
        "s3_presign_endpoint_url",
        "s3_bucket",
        "s3_access_key_id",
        "s3_secret_access_key",
    ):
        monkeypatch.setattr(worker.config.settings, name, getattr(settings, name))
    public_base = f"{settings.s3_endpoint_url}/{settings.s3_bucket}"
    monkeypatch.setattr(settings, "s3_public_base_url", public_base)
    monkeypatch.setattr(worker.config.settings, "s3_public_base_url", public_base)
    worker.storage.client.cache_clear()
    worker.storage.presign_client.cache_clear()
    monkeypatch.setattr(worker.config.settings, "tryon_provider", "mock")
    monkeypatch.setattr(worker.config.settings, "mock_duration_seconds", 0.6)
    monkeypatch.setattr(worker.config.settings, "mock_steps", 4)
    monkeypatch.setattr(worker.config.settings, "mock_fail", False)

    yield Stack(f"http://{live_server}", f"ws://{live_server}", sync_engine, rq_queue)

    app.dependency_overrides.pop(get_async_db, None)
    worker.storage.client.cache_clear()
    worker.storage.presign_client.cache_clear()
    sync_engine.dispose()
    await async_engine.dispose()
    with base.begin() as conn:
        conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
    base.dispose()


async def start_session_with_photo(http: httpx.AsyncClient) -> tuple[str, str]:
    session = (await http.post("/sessions", json={"consent_given": True})).json()["id"]
    r = await http.post(
        "/capture",
        data={"session_id": session},
        files={"file": ("me.jpg", make_image_bytes(800, 1200), "image/jpeg")},
    )
    assert r.status_code == 201, r.text
    return session, r.json()["key"]


async def start_job(http: httpx.AsyncClient, session: str, capture: str, products: list[str]) -> str:
    r = await http.post(
        "/tryon", json={"session_id": session, "capture_key": capture, "product_ids": products}
    )
    assert r.status_code == 202, r.text
    return r.json()["job_id"]


@dataclass
class Received:
    message: dict
    at: float


async def collect_until_terminal(ws, http: httpx.AsyncClient, job: str, timeout: float = 20.0):
    """Read job messages until done/failed. For each one, also read GET /jobs/{id} right away.

    Returns (messages, polls) where polls[i] is what the polling endpoint said as message i arrived.
    """
    received: list[Received] = []
    polls: list[dict] = []
    deadline = time.monotonic() + timeout
    while True:
        raw = await asyncio.wait_for(ws.recv(), max(0.1, deadline - time.monotonic()))
        message = json.loads(raw)
        if message == PING:
            continue
        received.append(Received(message, time.monotonic()))
        polls.append((await http.get(f"/jobs/{job}")).json())
        if message["status"] in ("done", "failed"):
            return received, polls


# --- tests ------------------------------------------------------------------------------------------


async def test_a_mock_job_streams_queued_then_progress_then_done_in_order(stack, aredis):
    async with httpx.AsyncClient(base_url=stack.http_base, timeout=15) as http:
        session, capture = await start_session_with_photo(http)
        products = [stack.add_product("Linen Camp Shirt"), stack.add_product("Wide-Leg Trouser", "bottom")]
        numpat_before = await aredis.pubsub_numpat()

        async with connect(stack.ws(session)) as ws:
            job = await start_job(http, session, capture, products)
            worker = asyncio.create_task(asyncio.to_thread(stack.run_worker))
            received, polls = await asyncio.wait_for(collect_until_terminal(ws, http, job), 20)
            await worker

            messages = [r.message for r in received]
            statuses = [m["status"] for m in messages]
            pcts = [m["pct"] for m in messages]

            # The order: queued, then progress, then exactly one done at the end.
            assert statuses[0] == "queued" and pcts[0] == 0
            assert statuses[-1] == "done" and pcts[-1] == 100
            progress = [m for m in messages if m["status"] == "processing"]
            assert statuses == ["queued"] + ["processing"] * len(progress) + ["done"]
            assert len(progress) >= 5
            # Percentages only ever move forward. Each progress step is a new value (queued and the first
            # processing message are both 0, which is the one allowed repeat).
            processing_pcts = [m["pct"] for m in progress]
            assert pcts == sorted(pcts)
            assert processing_pcts == sorted(set(processing_pcts))
            assert progress[0]["pct"] == 0 and 0 < progress[-1]["pct"] < 100
            assert any(20 < p["pct"] < 90 for p in progress)

            # The messages carry exactly the documented fields, and the job id throughout.
            assert {m["job"] for m in messages} == {job}
            assert all(set(m) == {"job", "status", "pct"} for m in messages[:-1])
            done = messages[-1]
            assert set(done) == {"job", "status", "pct", "url"} and done["url"].startswith("http")
            assert not any("session" in m for m in messages)

            # They arrived spread over the mock's run, not in one burst at the end.
            assert received[-1].at - received[1].at >= 0.4

            # Nothing follows `done`.
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(ws.recv(), 0.5)

        # Polling agreed with the stream throughout: the state is never behind a delivered message.
        for message, polled in zip(messages, polls, strict=True):
            assert polled["job"] == job and polled["pct"] >= message["pct"], (message, polled)
        assert polls[-1]["status"] == "done" and polls[-1]["url"] == done["url"]

        # The result is real, the database agrees, and the subscription is gone.
        result = await http.get(done["url"])
        assert result.status_code == 200 and result.content[:4] == b"RIFF" and b"WEBP" in result.content[:16]
        assert (await http.get(f"/tryon/{job}")).json()["status"] == "done"
        deadline = time.monotonic() + 3
        while await aredis.pubsub_numpat() != numpat_before and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        assert await aredis.pubsub_numpat() == numpat_before


async def test_a_failing_job_streams_queued_progress_then_failed_with_a_readable_error(stack, monkeypatch):
    import worker.config

    monkeypatch.setattr(worker.config.settings, "mock_fail", True)
    async with httpx.AsyncClient(base_url=stack.http_base, timeout=15) as http:
        session, capture = await start_session_with_photo(http)
        products = [stack.add_product("Linen Camp Shirt")]

        async with connect(stack.ws(session)) as ws:
            job = await start_job(http, session, capture, products)
            worker = asyncio.create_task(asyncio.to_thread(stack.run_worker))
            received, polls = await asyncio.wait_for(collect_until_terminal(ws, http, job), 20)
            await worker

        messages = [r.message for r in received]
        assert [m["status"] for m in messages][0] == "queued"
        assert messages[-1]["status"] == "failed" and "MOCK_FAIL" in messages[-1]["error"]
        assert "url" not in messages[-1]
        assert all(m["status"] != "done" for m in messages)
        assert [m["pct"] for m in messages] == sorted(m["pct"] for m in messages)
        assert polls[-1]["status"] == "failed" and polls[-1]["error"] == messages[-1]["error"]


async def test_a_client_that_reconnects_mid_job_catches_up_from_the_polling_endpoint(stack):
    async with httpx.AsyncClient(base_url=stack.http_base, timeout=15) as http:
        session, capture = await start_session_with_photo(http)
        products = [stack.add_product("Linen Camp Shirt")]

        ws = await connect(stack.ws(session))
        job = await start_job(http, session, capture, products)
        worker = asyncio.create_task(asyncio.to_thread(stack.run_worker))
        seen = []
        while not seen or seen[-1]["pct"] < 30:  # watch a little of the progress...
            message = json.loads(await asyncio.wait_for(ws.recv(), 5))
            if message != PING:
                seen.append(message)
        ws.transport.abort()  # ...then the network drops

        await asyncio.wait_for(worker, 20)  # the job carries on without anyone listening

        # Reconnect: the socket has no history, so the state comes from GET /jobs/{id}.
        async with connect(stack.ws(session)) as again:
            polled = (await http.get(f"/jobs/{job}")).json()
            assert polled["status"] == "done" and polled["pct"] == 100 and polled["url"].startswith("http")
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(again.recv(), 0.4)  # nothing is replayed
