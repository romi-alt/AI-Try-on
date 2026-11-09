import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class OrderStatus(enum.StrEnum):
    placed = "placed"  # waiting to be paid for and collected at the counter
    collected = "collected"  # paid for and handed over
    cancelled = "cancelled"  # not going ahead; its items went back into stock


class Order(Base):
    """A placed order: the cart as it was at checkout, with prices copied so catalog edits cannot alter it."""

    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("pickup_code", name="uq_orders_pickup_code"),
        # A retried checkout (same key, same session) finds its order instead of making a second one.
        UniqueConstraint("session_id", "idempotency_key", name="uq_orders_session_idempotency_key"),
        CheckConstraint("subtotal_pkr >= 0", name="ck_orders_subtotal_nonneg"),
        Index("ix_orders_created_at", "created_at"),
        Index("ix_orders_status_created_at", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Kept if the session is ever deleted: an order is a business record.
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="SET NULL")
    )
    idempotency_key: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    pickup_code: Mapped[str] = mapped_column(String(12), nullable=False)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False)
    subtotal_pkr: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, name="order_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=OrderStatus.placed,
        server_default=OrderStatus.placed.value,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # When it was last collected or cancelled; null while it is still waiting.
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    items = relationship(
        "OrderItem", back_populates="order", cascade="all, delete-orphan", order_by="OrderItem.position"
    )


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_order_items_quantity_positive"),
        Index("ix_order_items_order_id", "order_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    # Not a foreign key, so history survives a product being deleted (as with tryon_jobs.product_ids).
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    product_name: Mapped[str] = mapped_column(String(200), nullable=False)
    garment_image_url: Mapped[str] = mapped_column(Text, nullable=False)
    size: Mapped[str | None] = mapped_column(String(20))
    color: Mapped[str | None] = mapped_column(String(40))
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price_pkr: Mapped[int] = mapped_column(Integer, nullable=False)
    line_total_pkr: Mapped[int] = mapped_column(BigInteger, nullable=False)

    order = relationship("Order", back_populates="items")
