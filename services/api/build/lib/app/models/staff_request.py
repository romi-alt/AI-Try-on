import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class StaffRequestStatus(enum.StrEnum):
    open = "open"  # the shopper asked for the item to be brought to them
    bringing = "bringing"  # a staff member is on their way with it
    done = "done"


class StaffRequest(Base):
    """ "Request Outfit": a shopper at the mirror asks staff to bring an item (in a size) to them."""

    __tablename__ = "staff_requests"
    __table_args__ = (Index("ix_staff_requests_status_created", "status", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    # Copied, not a foreign key: staff need to read the request even if the product is edited or deleted.
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    product_name: Mapped[str] = mapped_column(String(200), nullable=False)
    size: Mapped[str | None] = mapped_column(String(20))
    color: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[StaffRequestStatus] = mapped_column(
        Enum(StaffRequestStatus, name="staff_request_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=StaffRequestStatus.open,
        server_default=StaffRequestStatus.open.value,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
