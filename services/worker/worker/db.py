"""Database access for the worker.

The worker does not import the API's ORM models; it talks to the two tables it needs through
SQLAlchemy Core so the services deploy independently. The schema is owned by services/api/alembic;
`tests/test_schema_contract.py` checks these definitions against a migrated database.
"""

import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import ARRAY, ENUM, UUID

from worker.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
metadata = MetaData()


def _discard_inherited_connections() -> None:
    """RQ forks a child per job. A child that inherited the parent's pooled connections would share
    their sockets with it (psycopg then fails with "prepared statement already exists"). Drop them
    in the child without closing them, so the parent keeps using its own."""
    engine.dispose(close=False)


os.register_at_fork(after_in_child=_discard_inherited_connections)

JOB_STATUSES = ("queued", "processing", "done", "failed")
PRODUCT_CATEGORIES = ("top", "bottom", "dress", "shoes", "bag", "accessory")

job_status = ENUM(*JOB_STATUSES, name="job_status", create_type=False)
product_category = ENUM(*PRODUCT_CATEGORIES, name="product_category", create_type=False)

tryon_jobs = Table(
    "tryon_jobs",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("session_id", UUID(as_uuid=True), nullable=False),
    Column("product_ids", ARRAY(UUID(as_uuid=True)), nullable=False),
    Column("status", job_status, nullable=False),
    Column("progress", Integer, nullable=False),
    Column("person_image_key", String(512), nullable=False),
    Column("result_url", Text),
    Column("error", Text),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)
products = Table(
    "products",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("name", String(200), nullable=False),
    Column("category", product_category, nullable=False),
    Column("garment_image_url", Text, nullable=False),
    Column("garment_mask_url", Text),
)


@dataclass(frozen=True)
class JobRow:
    id: uuid.UUID
    session_id: uuid.UUID
    product_ids: list[uuid.UUID]
    status: str
    progress: int
    person_image_key: str


@dataclass(frozen=True)
class ProductRow:
    id: uuid.UUID
    name: str
    category: str
    garment_image_url: str


def _now() -> datetime:
    return datetime.now(UTC)


def fetch_job(job_id: uuid.UUID) -> JobRow | None:
    with engine.connect() as conn:
        row = conn.execute(select(tryon_jobs).where(tryon_jobs.c.id == job_id)).first()
    if row is None:
        return None
    return JobRow(
        id=row.id,
        session_id=row.session_id,
        product_ids=list(row.product_ids),
        status=row.status,
        progress=row.progress,
        person_image_key=row.person_image_key,
    )


def fetch_products(product_ids: list[uuid.UUID]) -> dict[uuid.UUID, ProductRow]:
    with engine.connect() as conn:
        rows = conn.execute(select(products).where(products.c.id.in_(product_ids))).all()
    return {
        r.id: ProductRow(id=r.id, name=r.name, category=r.category, garment_image_url=r.garment_image_url)
        for r in rows
    }


def claim_job(job_id: uuid.UUID) -> bool:
    """queued -> processing, atomically. False if another worker already took it (or it is done)."""
    stmt = (
        update(tryon_jobs)
        .where(tryon_jobs.c.id == job_id, tryon_jobs.c.status == "queued")
        .values(status="processing", progress=0, error=None, updated_at=_now())
    )
    with engine.begin() as conn:
        return conn.execute(stmt).rowcount == 1


def set_progress(job_id: uuid.UUID, pct: int) -> None:
    stmt = (
        update(tryon_jobs)
        .where(tryon_jobs.c.id == job_id, tryon_jobs.c.status == "processing")
        .values(progress=pct, updated_at=_now())
    )
    with engine.begin() as conn:
        conn.execute(stmt)


def mark_done(job_id: uuid.UUID, result_url: str) -> None:
    stmt = (
        update(tryon_jobs)
        .where(tryon_jobs.c.id == job_id)
        .values(status="done", progress=100, result_url=result_url, error=None, updated_at=_now())
    )
    with engine.begin() as conn:
        conn.execute(stmt)


def mark_failed(job_id: uuid.UUID, error: str) -> bool:
    """Fail a job that has not finished. False (and no change) if it was already done/failed."""
    stmt = (
        update(tryon_jobs)
        .where(tryon_jobs.c.id == job_id, tryon_jobs.c.status.in_(("queued", "processing")))
        .values(status="failed", error=error[:2000], updated_at=_now())
    )
    with engine.begin() as conn:
        return conn.execute(stmt).rowcount == 1


def fail_stale_processing(older_than: timedelta, error: str) -> list[tuple[uuid.UUID, uuid.UUID, int]]:
    """Fail jobs stuck in `processing` with no update for `older_than`.

    Returns (job id, session id, progress) for each, so the caller can announce the failure.
    """
    stmt = (
        update(tryon_jobs)
        .where(tryon_jobs.c.status == "processing", tryon_jobs.c.updated_at < _now() - older_than)
        .values(status="failed", error=error[:2000], updated_at=_now())
        .returning(tryon_jobs.c.id, tryon_jobs.c.session_id, tryon_jobs.c.progress)
    )
    with engine.begin() as conn:
        return [(r.id, r.session_id, r.progress) for r in conn.execute(stmt)]


def ping() -> None:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
