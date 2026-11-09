"""Minimal DB access for the worker.

The worker deliberately does not import the API's ORM models; it talks to the
two tables it needs via SQLAlchemy Core so the services can be deployed and
versioned independently. Schema is owned by services/api/alembic.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

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
from sqlalchemy.dialects.postgresql import UUID

from worker.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
metadata = MetaData()

# Only the columns the worker touches. Declared explicitly (no reflection) so the
# module imports without a live database; the schema is owned by services/api/alembic.
tryon_jobs = Table(
    "tryon_jobs",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("garment_id", UUID(as_uuid=True), nullable=False),
    Column("status", String(20), nullable=False),
    Column("capture_key", String(512), nullable=False),
    Column("result_key", String(512)),
    Column("error", Text),
    Column("provider", String(60)),
    Column("duration_ms", Integer),
    Column("updated_at", DateTime(timezone=True)),
)
garments = Table(
    "garments",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("image_key", String(512), nullable=False),
    Column("category", String(20), nullable=False),
)


@dataclass
class JobRow:
    id: uuid.UUID
    status: str
    capture_key: str
    garment_id: uuid.UUID
    garment_image_key: str
    garment_category: str


def fetch_job(job_id: uuid.UUID) -> JobRow | None:
    stmt = (
        select(
            tryon_jobs.c.id,
            tryon_jobs.c.status,
            tryon_jobs.c.capture_key,
            tryon_jobs.c.garment_id,
            garments.c.image_key,
            garments.c.category,
        )
        .join(garments, garments.c.id == tryon_jobs.c.garment_id)
        .where(tryon_jobs.c.id == job_id)
    )
    with engine.connect() as conn:
        row = conn.execute(stmt).first()
    if not row:
        return None
    return JobRow(
        id=row.id,
        status=row.status,
        capture_key=row.capture_key,
        garment_id=row.garment_id,
        garment_image_key=row.image_key,
        garment_category=str(row.category),
    )


def mark_processing(job_id: uuid.UUID, provider: str) -> bool:
    """Atomically claim the job. Returns False if someone else already did."""
    stmt = (
        update(tryon_jobs)
        .where(tryon_jobs.c.id == job_id, tryon_jobs.c.status == "queued")
        .values(status="processing", provider=provider, updated_at=datetime.now(UTC))
    )
    with engine.begin() as conn:
        return conn.execute(stmt).rowcount == 1


def mark_done(job_id: uuid.UUID, result_key: str, duration_ms: int) -> None:
    stmt = (
        update(tryon_jobs)
        .where(tryon_jobs.c.id == job_id)
        .values(
            status="done",
            result_key=result_key,
            duration_ms=duration_ms,
            error=None,
            updated_at=datetime.now(UTC),
        )
    )
    with engine.begin() as conn:
        conn.execute(stmt)


def mark_failed(job_id: uuid.UUID, error: str, duration_ms: int | None = None) -> None:
    stmt = (
        update(tryon_jobs)
        .where(tryon_jobs.c.id == job_id)
        .values(status="failed", error=error[:2000], duration_ms=duration_ms, updated_at=datetime.now(UTC))
    )
    with engine.begin() as conn:
        conn.execute(stmt)


def ping() -> None:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
