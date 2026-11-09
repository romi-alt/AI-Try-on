import enum
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, Enum, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

EMBEDDING_DIM = 512


class GarmentCategory(enum.StrEnum):
    top = "top"
    bottom = "bottom"
    dress = "dress"
    outerwear = "outerwear"
    accessory = "accessory"


class Garment(Base):
    __tablename__ = "garments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sku: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    brand: Mapped[str | None] = mapped_column(String(120))
    category: Mapped[GarmentCategory] = mapped_column(
        Enum(GarmentCategory, name="garment_category", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    color: Mapped[str | None] = mapped_column(String(60))
    price_cents: Mapped[int | None] = mapped_column(Integer)
    image_key: Mapped[str] = mapped_column(String(512), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    # CLIP-style image embedding for "similar garments" lookups via pgvector.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
