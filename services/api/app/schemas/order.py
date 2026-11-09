import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.models.order import OrderStatus


class CheckoutIn(BaseModel):
    session_id: uuid.UUID
    # Make one per checkout attempt and resend it on a retry: the same key returns the order already placed
    # instead of placing a second one (a lost response would otherwise look like a failure).
    idempotency_key: uuid.UUID | None = None


class OrderItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_id: uuid.UUID
    product_name: str
    garment_image_url: str
    size: str | None
    color: str | None
    quantity: int
    unit_price_pkr: int
    line_total_pkr: int


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    session_id: uuid.UUID | None
    pickup_code: str
    status: OrderStatus
    item_count: int
    subtotal_pkr: int
    created_at: datetime
    status_changed_at: datetime | None
    items: list[OrderItemOut]


class OrderStatusIn(BaseModel):
    # An order starts as "placed"; staff can only close it, one way or the other.
    status: Literal["collected", "cancelled"]
