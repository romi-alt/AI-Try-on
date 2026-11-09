import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class KioskSession(Base):
    """One shopper interaction at the mirror."""

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Shopper agreed to webcam capture / image processing.
    consent_given: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    jobs = relationship("TryOnJob", back_populates="session", cascade="all, delete-orphan")
    cart = relationship("Cart", back_populates="session", cascade="all, delete-orphan", uselist=False)
