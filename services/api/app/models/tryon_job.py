import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class JobStatus(enum.StrEnum):
    queued = "queued"
    processing = "processing"
    done = "done"
    failed = "failed"


class TryOnJob(Base):
    __tablename__ = "tryon_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    garment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("garments.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=JobStatus.queued,
        server_default="queued",
    )
    capture_key: Mapped[str] = mapped_column(String(512), nullable=False)
    result_key: Mapped[str | None] = mapped_column(String(512))
    error: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[str | None] = mapped_column(String(60))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    session = relationship("KioskSession", back_populates="jobs")
    garment = relationship("Garment")
