import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.models.product import ProductCategory

MAX_QUANTITY_PER_ADD = 10


class CartAddIn(BaseModel):
    session_id: uuid.UUID
    product_id: uuid.UUID
    size: str | None = Field(default=None, max_length=20)
    color: str | None = Field(default=None, max_length=40, description="Color name, as listed on the product")
    quantity: int = Field(default=1, ge=1, le=MAX_QUANTITY_PER_ADD)


class CartProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    category: ProductCategory
    garment_image_url: str


class CartItemOut(BaseModel):
    id: uuid.UUID
    product: CartProductOut
    size: str | None
    color: str | None
    quantity: int
    unit_price_pkr: int
    line_total_pkr: int


class CartOut(BaseModel):
    session_id: uuid.UUID
    cart_id: uuid.UUID | None
    items: list[CartItemOut]
    item_count: int
    subtotal_pkr: int
