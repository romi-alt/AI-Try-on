import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ShareLink(Base):
    """A short code for the mobile page `/m/{short_code}`: a look image, the shopper's cart and a checkout
    button.

    The code is the only credential (it is in a QR code the shopper scans), so it is random and expires.
    """

    __tablename__ = "share_links"
    __table_args__ = (
        UniqueConstraint("short_code", name="uq_share_links_short_code"),
        Index("ix_share_links_session_id", "session_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    short_code: Mapped[str] = mapped_column(String(16), nullable=False)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    # The look shown on the page. Not a foreign key: the job is a historical record.
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
