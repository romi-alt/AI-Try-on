import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.product import ProductCategory


class ColorOption(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    hex: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")


class ProductBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    category: ProductCategory
    price_pkr: int = Field(ge=0)
    sale_price_pkr: int | None = Field(default=None, ge=0)
    sizes: list[str] = Field(default_factory=list)
    colors: list[ColorOption] = Field(default_factory=list)
    stock: int = Field(default=0, ge=0)
    garment_image_url: str = Field(min_length=1)
    garment_mask_url: str | None = None

    @model_validator(mode="after")
    def _sale_not_above_price(self):
        if self.sale_price_pkr is not None and self.sale_price_pkr > self.price_pkr:
            raise ValueError("sale_price_pkr cannot exceed price_pkr")
        return self


class ProductCreate(ProductBase):
    pass


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    category: ProductCategory | None = None
    price_pkr: int | None = Field(default=None, ge=0)
    sale_price_pkr: int | None = Field(default=None, ge=0)
    sizes: list[str] | None = None
    colors: list[ColorOption] | None = None
    stock: int | None = Field(default=None, ge=0)
    garment_image_url: str | None = Field(default=None, min_length=1)
    garment_mask_url: str | None = None


class ProductOut(ProductBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    on_sale: bool
    current_price_pkr: int


class SimilarProductOut(ProductOut):
    # Cosine distance to the reference item; None when no embedding is available and the item is a plain
    # fallback.
    distance: float | None
