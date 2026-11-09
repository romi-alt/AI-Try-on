"""Shared fixtures for route tests.

DB-backed tests need a migrated Postgres (`make migrate`) and skip when none is reachable.
Each test runs inside one transaction on a dedicated connection that is rolled back at the end,
so nothing leaks into the dev database and tests can run alongside seeded data. The app's
`get_async_db` dependency is overridden to use that same transaction.
"""

import socket
import sys
import threading
import time
import uuid
from collections.abc import AsyncGenerator, Generator
from pathlib import Path

import boto3
import httpx
import pytest
import redis
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core import storage
from app.core.config import settings
from app.core.db import get_async_db
from app.main import app

# The cross-service integration test imports the worker package. It lives next to this one in the repo
# (`services/worker`), and docker-compose mounts it at /worker, so `parents[2] / "worker"` is right in both.
_WORKER_DIR = Path(__file__).resolve().parents[2] / "worker"
if _WORKER_DIR.is_dir() and str(_WORKER_DIR) not in sys.path:
    sys.path.append(str(_WORKER_DIR))  # appended: never shadows anything the API itself provides


@pytest.fixture
async def adb() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        conn = await engine.connect()
    except Exception:
        await engine.dispose()
        pytest.skip("Postgres not reachable")
    migrated = await conn.run_sync(lambda c: "cart_items" in inspect(c).get_table_names())
    await conn.rollback()
    if not migrated:
        await conn.close()
        await engine.dispose()
        pytest.skip("database not migrated (run `make migrate`)")

    trans = await conn.begin()
    session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
    try:
        yield session
    finally:
        await session.close()
        await trans.rollback()
        await conn.close()
        await engine.dispose()


@pytest.fixture
async def api(adb: AsyncSession) -> AsyncGenerator[httpx.AsyncClient, None]:
    async def _override() -> AsyncGenerator[AsyncSession, None]:
        yield adb

    app.dependency_overrides[get_async_db] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.pop(get_async_db, None)


@pytest.fixture
async def plain_api() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Client with no DB override, for routes/middleware that never touch the database."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def token() -> str:
    """Unique string to put in product names so tests can isolate their rows from seed data."""
    return "zz" + uuid.uuid4().hex[:10]


# --- S3-compatible storage (moto server) ------------------------------------------------------


@pytest.fixture(scope="session")
def s3_server() -> Generator[str, None, None]:
    """A real S3 HTTP server in a thread, so boto3 and presigned URLs behave as against MinIO/R2."""
    from moto.server import ThreadedMotoServer

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = ThreadedMotoServer(ip_address="127.0.0.1", port=port, verbose=False)
    server.start()
    yield f"http://127.0.0.1:{port}"
    server.stop()


@pytest.fixture
def s3(s3_server: str, monkeypatch: pytest.MonkeyPatch):
    """Point the app at a fresh empty bucket on the moto server. Returns a boto3 client."""
    bucket = f"test-{uuid.uuid4().hex[:12]}"
    for name, value in {
        "s3_endpoint_url": s3_server,
        "s3_presign_endpoint_url": s3_server,
        "s3_bucket": bucket,
        "s3_access_key_id": "test",
        "s3_secret_access_key": "test",
    }.items():
        monkeypatch.setattr(settings, name, value)
    storage.internal_client.cache_clear()
    storage.presign_client.cache_clear()
    client = boto3.client(
        "s3",
        endpoint_url=s3_server,
        region_name="us-east-1",  # moto rejects CreateBucket under R2's "auto"; the app still uses "auto"
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
    client.create_bucket(Bucket=bucket)
    yield client
    storage.internal_client.cache_clear()
    storage.presign_client.cache_clear()


# --- Redis / RQ -------------------------------------------------------------------------------


@pytest.fixture
def rq_queue(monkeypatch: pytest.MonkeyPatch):
    """A uniquely named RQ queue on the real Redis, emptied afterwards. Skips without Redis."""
    try:
        redis.Redis.from_url(settings.redis_url, socket_connect_timeout=1).ping()
    except redis.RedisError:
        pytest.skip("Redis not reachable")
    from app.services.queue import get_queue

    monkeypatch.setattr(settings, "tryon_queue_name", f"test-{uuid.uuid4().hex[:10]}")
    queue = get_queue()
    conn = redis.Redis.from_url(settings.redis_url)
    existing = set(conn.scan_iter("job:*"))
    yield queue
    queue.empty()
    if created := set(conn.scan_iter("job:*")) - existing:  # job state hashes written during the test
        conn.delete(*created)


@pytest.fixture
def assets_queue(monkeypatch: pytest.MonkeyPatch):
    """A uniquely named assets queue on the real Redis, emptied afterwards. Skips without Redis."""
    try:
        redis.Redis.from_url(settings.redis_url, socket_connect_timeout=1).ping()
    except redis.RedisError:
        pytest.skip("Redis not reachable")
    from app.services.queue import get_assets_queue

    monkeypatch.setattr(settings, "assets_queue_name", f"test-assets-{uuid.uuid4().hex[:10]}")
    queue = get_assets_queue()
    yield queue
    queue.empty()


# --- live server + Redis for WebSocket tests ----------------------------------------------------------


@pytest.fixture(scope="module")
def live_server():
    """The real app served by uvicorn in a thread, so WebSocket tests use the real protocol and server."""
    import uvicorn

    try:  # every WebSocket test needs Redis, so skip them all up front when it is not there
        redis.Redis.from_url(settings.redis_url, socket_connect_timeout=1).ping()
    except redis.RedisError:
        pytest.skip("Redis not reachable")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None, lifespan="off")  # no sweeper task
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("uvicorn did not start")
        time.sleep(0.05)
    yield f"127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture
async def aredis() -> AsyncGenerator["redis.asyncio.Redis", None]:
    import redis.asyncio as aioredis

    conn = aioredis.Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        await conn.ping()
    except redis.RedisError:
        await conn.aclose()
        pytest.skip("Redis not reachable")
    yield conn
    await conn.aclose()
