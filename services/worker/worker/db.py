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
    func,
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
    Column(
        "recommended_product_ids",
        ARRAY(UUID(as_uuid=True)),
        nullable=False,
        server_default=text("'{}'::uuid[]"),
    ),
    Column("result_url", Text),
    Column("error", Text),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)
PROCESSING_STATUSES = ("idle", "queued", "processing", "done", "failed")
processing_status = ENUM(*PROCESSING_STATUSES, name="processing_status", create_type=False)

# The `embedding vector(512)` column is written with raw SQL (see `set_embedding`), so the worker does not
# need the pgvector package just to declare it.
products = Table(
    "products",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("name", String(200), nullable=False),
    Column("category", product_category, nullable=False),
    Column("garment_image_url", Text, nullable=False),
    Column("garment_mask_url", Text),
    Column("garment_original_url", Text),
    Column("embedding_updated_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("processing_status", processing_status, nullable=False, server_default="idle"),
    Column("processing_error", Text),
    Column("processing_updated_at", DateTime(timezone=True)),
)


@dataclass(frozen=True)
class JobRow:
    id: uuid.UUID
    session_id: uuid.UUID
    product_ids: list[uuid.UUID]
    status: str
    progress: int
    person_image_key: str
    recommended_product_ids: list[uuid.UUID]
    created_at: datetime | None


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
        recommended_product_ids=list(row.recommended_product_ids or []),
        created_at=row.created_at,
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


# --- product assets (embeddings, background removal) -----------------------------------------------------


@dataclass(frozen=True)
class ProductImageRow:
    id: uuid.UUID
    name: str
    garment_image_url: str
    garment_original_url: str | None
    has_embedding: bool


def list_product_images(
    product_ids: list[uuid.UUID] | None = None, *, only_missing: bool = False
) -> list[ProductImageRow]:
    """Products to embed or process, in a stable order. `only_missing` keeps those with no embedding yet."""
    query = """
        SELECT id, name, garment_image_url, garment_original_url, embedding IS NOT NULL AS has_embedding
        FROM products
        WHERE (CAST(:ids AS uuid[]) IS NULL OR id = ANY(CAST(:ids AS uuid[])))
          AND (NOT :only_missing OR embedding IS NULL)
        ORDER BY created_at, id
    """
    with engine.connect() as conn:
        rows = conn.execute(text(query), {"ids": product_ids, "only_missing": only_missing}).all()
    return [
        ProductImageRow(r.id, r.name, r.garment_image_url, r.garment_original_url, r.has_embedding)
        for r in rows
    ]


def set_embedding(product_id: uuid.UUID, vector: list[float]) -> bool:
    """Store a product's embedding. False if the product no longer exists."""
    literal = "[" + ",".join(f"{x:.8f}" for x in vector) + "]"
    stmt = text(
        "UPDATE products SET embedding = CAST(:v AS vector), embedding_updated_at = now() WHERE id = :id"
    )
    with engine.begin() as conn:
        return conn.execute(stmt, {"v": literal, "id": product_id}).rowcount == 1


def claim_processing(product_id: uuid.UUID) -> bool:
    """queued -> processing. False if another worker took it, it was never queued, or the product is gone."""
    stmt = (
        update(products)
        .where(products.c.id == product_id, products.c.processing_status == "queued")
        .values(processing_status="processing", processing_error=None, processing_updated_at=_now())
    )
    with engine.begin() as conn:
        return conn.execute(stmt).rowcount == 1


def finish_processing(product_id: uuid.UUID, *, image_url: str, mask_url: str, original_url: str) -> None:
    stmt = (
        update(products)
        .where(products.c.id == product_id)
        .values(
            garment_image_url=image_url,
            garment_mask_url=mask_url,
            garment_original_url=original_url,
            processing_status="done",
            processing_error=None,
            processing_updated_at=_now(),
        )
    )
    with engine.begin() as conn:
        conn.execute(stmt)


def fail_processing(product_id: uuid.UUID, message: str) -> None:
    stmt = (
        update(products)
        .where(products.c.id == product_id)
        .values(processing_status="failed", processing_error=message[:1000], processing_updated_at=_now())
    )
    with engine.begin() as conn:
        conn.execute(stmt)
