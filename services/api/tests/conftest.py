"""Shared fixtures for route tests.

DB-backed tests need a migrated Postgres (`make migrate`) and skip when none is reachable.
Each test runs inside one transaction on a dedicated connection that is rolled back at the end,
so nothing leaks into the dev database and tests can run alongside seeded data. The app's
`get_async_db` dependency is overridden to use that same transaction.
"""

import uuid
from collections.abc import AsyncGenerator

import httpx
import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.db import get_async_db
from app.main import app


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
