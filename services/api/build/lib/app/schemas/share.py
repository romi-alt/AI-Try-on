import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.cart import CartItemOut
from app.schemas.order import OrderOut


class ShareCreate(BaseModel):
    session_id: uuid.UUID
    job_id: uuid.UUID | None = Field(
        default=None, description="The look to show; must be a finished job of the session"
    )


class ShareOut(BaseModel):
    short_code: str
    path: str = Field(description="Path of the mobile page, e.g. /m/K7TQ4M2X")
    expires_at: datetime


class MobileCartOut(BaseModel):
    """The cart as the mobile page sees it: no session or cart ids, the short code is the only handle."""

    items: list[CartItemOut]
    item_count: int
    subtotal_pkr: int


class MobileLookOut(BaseModel):
    short_code: str
    expires_at: datetime
    look_image_url: str | None
    cart: MobileCartOut
    # The newest order the shopper placed from this session since the code was made (it empties the cart).
    order: OrderOut | None


class MobileCheckoutIn(BaseModel):
    idempotency_key: uuid.UUID | None = None


class PaymentOut(BaseModel):
    provider: str
    status: str
    reference: str
    redirect_url: str | None


class MobileCheckoutOut(BaseModel):
    order: OrderOut
    payment: PaymentOut
