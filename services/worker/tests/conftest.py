"""Fixtures: a throwaway Postgres schema, a moto S3 server, and real Redis pub/sub.

Tests skip (rather than fail) when Postgres or Redis is not reachable.
"""

import json
import socket
import uuid
from collections.abc import Generator

import boto3
import pytest
import redis
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from worker import db, storage
from worker.config import settings


@pytest.fixture(scope="session")
def s3_server() -> Generator[str, None, None]:
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
    bucket = f"test-{uuid.uuid4().hex[:12]}"
    for name, value in {
        "s3_endpoint_url": s3_server,
        "s3_presign_endpoint_url": s3_server,
        "s3_bucket": bucket,
        "s3_public_base_url": f"{s3_server}/{bucket}",
        "s3_access_key_id": "test",
        "s3_secret_access_key": "test",
    }.items():
        monkeypatch.setattr(settings, name, value)
    storage.client.cache_clear()
    storage.presign_client.cache_clear()
    client = boto3.client(
        "s3",
        endpoint_url=s3_server,
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
    client.create_bucket(Bucket=bucket)
    yield client
    storage.client.cache_clear()
    storage.presign_client.cache_clear()


@pytest.fixture
def pg(monkeypatch: pytest.MonkeyPatch):
    """The worker's two tables in a private schema, so tests never touch real data."""
    base = create_engine(settings.database_url)
    try:
        base.connect().close()
    except OperationalError:
        base.dispose()
        pytest.skip("Postgres not reachable")
    schema = f"t_{uuid.uuid4().hex[:10]}"
    with base.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    # `public` stays on the path so pgvector's type and operators resolve, as in a real deployment.
    engine = create_engine(settings.database_url, connect_args={"options": f"-csearch_path={schema},public"})
    with engine.begin() as conn:
        for name, values in (
            ("job_status", db.JOB_STATUSES),
            ("product_category", db.PRODUCT_CATEGORIES),
            ("processing_status", db.PROCESSING_STATUSES),
        ):
            conn.execute(text(f"CREATE TYPE {schema}.{name} AS ENUM ({', '.join(repr(v) for v in values)})"))
    db.metadata.create_all(engine, checkfirst=False)  # a checkfirst would see the real tables in `public`
    with (
        engine.begin() as conn
    ):  # declared in SQL, not in the Table: the worker never needs the pgvector package
        conn.execute(text(f"ALTER TABLE {schema}.products ADD COLUMN embedding vector(512)"))
    monkeypatch.setattr(db, "engine", engine)
    yield engine
    engine.dispose()
    with base.begin() as conn:
        conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
    base.dispose()


@pytest.fixture
def redis_conn() -> Generator[redis.Redis, None, None]:
    conn = redis.Redis.from_url(settings.redis_url)
    try:
        conn.ping()
    except redis.RedisError:
        pytest.skip("Redis not reachable")
    yield conn
    conn.close()


class Listener:
    """Subscribes to a session's job channel; `messages()` returns everything received so far."""

    def __init__(self, conn: redis.Redis, session_id):
        self.pubsub = conn.pubsub()
        self.pubsub.subscribe(f"session:{session_id}:job")
        assert self.pubsub.get_message(timeout=2)["type"] == "subscribe"

    def messages(self) -> list[dict]:
        out = []
        while (m := self.pubsub.get_message(timeout=0.3)) is not None:
            if m["type"] == "message":
                out.append(json.loads(m["data"]))
        return out

    def close(self):
        self.pubsub.close()


@pytest.fixture
def listen(redis_conn):
    made = []

    def factory(session_id) -> Listener:
        made.append(Listener(redis_conn, session_id))
        return made[-1]

    yield factory
    for listener in made:
        listener.close()


@pytest.fixture(autouse=True)
def fast_mock(monkeypatch: pytest.MonkeyPatch):
    """Tests never wait the real 8 seconds."""
    monkeypatch.setattr(settings, "mock_duration_seconds", 0.0)
    monkeypatch.setattr(settings, "mock_steps", 4)
    monkeypatch.setattr(settings, "mock_fail", False)
    monkeypatch.setattr(settings, "tryon_provider", "mock")
