import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class StatsOut(BaseModel):
    products_in_stock: int
    sessions_today: int
    jobs_today: int
    jobs_failed_today: int
    queue_depth: int


class ProductTryOnStats(BaseModel):
    product_id: uuid.UUID
    name: str
    category: str | None
    tryons: int
    added_to_cart: int
    cart_rate: float | None = Field(description="added_to_cart / tryons, 0 to 1")


class PairingStats(BaseModel):
    base_product_id: uuid.UUID
    base_name: str
    recommended_product_id: uuid.UUID
    recommended_name: str
    tryons: int
    added_to_cart: int


class AnalyticsOut(BaseModel):
    days: int
    since: datetime
    tryons: int = Field(description="Finished try-on looks in the period")
    tryons_with_cart: int = Field(description="Looks after which one of their items went into the cart")
    cart_rate: float | None = Field(description="tryons_with_cart / tryons, 0 to 1; null with no try-ons")
    products: list[ProductTryOnStats]
    pairings: list[PairingStats]
