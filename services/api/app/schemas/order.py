import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


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
    item_count: int
    subtotal_pkr: int
    created_at: datetime
    items: list[OrderItemOut]
