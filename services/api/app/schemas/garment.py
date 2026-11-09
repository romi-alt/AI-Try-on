import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.core.storage import public_url
from app.models.garment import GarmentCategory


class GarmentBase(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    brand: str | None = Field(default=None, max_length=120)
    category: GarmentCategory
    color: str | None = Field(default=None, max_length=60)
    price_cents: int | None = Field(default=None, ge=0)
    image_key: str = Field(min_length=1, max_length=512)
    is_active: bool = True


class GarmentCreate(GarmentBase):
    pass


class GarmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    brand: str | None = None
    category: GarmentCategory | None = None
    color: str | None = None
    price_cents: int | None = Field(default=None, ge=0)
    image_key: str | None = None
    is_active: bool | None = None


class GarmentOut(GarmentBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def image_url(self) -> str:
        return public_url(self.image_key)


class SimilarGarmentOut(GarmentOut):
    distance: float
