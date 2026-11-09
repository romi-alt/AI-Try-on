import enum
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class JobStatus(enum.StrEnum):
    queued = "queued"
    processing = "processing"
    done = "done"
    failed = "failed"


class TryOnJob(Base):
    __tablename__ = "tryon_jobs"
    __table_args__ = (
        CheckConstraint("progress BETWEEN 0 AND 100", name="ck_tryon_jobs_progress_range"),
        CheckConstraint("cardinality(product_ids) >= 1", name="ck_tryon_jobs_has_products"),
        Index("ix_tryon_jobs_session_id", "session_id"),
        Index("ix_tryon_jobs_status_created", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    # Products rendered together (outfit). Plain array, not a FK: a job is a historical record
    # and must survive catalog changes.
    product_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=JobStatus.queued,
        server_default="queued",
    )
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    person_image_key: Mapped[str] = mapped_column(String(512), nullable=False)
    result_url: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    session = relationship("KioskSession", back_populates="jobs")
