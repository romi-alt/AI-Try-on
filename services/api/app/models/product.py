import enum
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

EMBEDDING_DIM = 512


class ProductCategory(enum.StrEnum):
    top = "top"
    bottom = "bottom"
    dress = "dress"
    shoes = "shoes"
    bag = "bag"
    accessory = "accessory"


class ProcessingStatus(enum.StrEnum):
    idle = "idle"  # never processed, or processing was not asked for
    queued = "queued"
    processing = "processing"
    done = "done"
    failed = "failed"


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("price_pkr >= 0", name="ck_products_price_nonneg"),
        CheckConstraint(
            "sale_price_pkr IS NULL OR (sale_price_pkr >= 0 AND sale_price_pkr <= price_pkr)",
            name="ck_products_sale_price_valid",
        ),
        CheckConstraint("stock >= 0", name="ck_products_stock_nonneg"),
        UniqueConstraint("sku", name="uq_products_sku"),
        Index("ix_products_category", "category"),
        # Cosine-distance ANN index for "similar products" lookups.
        Index(
            "ix_products_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Optional stock-keeping unit: the key CSV imports use to update an existing product.
    sku: Mapped[str | None] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[ProductCategory] = mapped_column(
        Enum(ProductCategory, name="product_category", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    # Whole Pakistani rupees. No paisa precision is needed for retail pricing.
    price_pkr: Mapped[int] = mapped_column(Integer, nullable=False)
    sale_price_pkr: Mapped[int | None] = mapped_column(Integer)
    # e.g. ["S", "M", "L"] or ["38", "39"]
    sizes: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # e.g. [{"name": "Ivory", "hex": "#f2ead9"}]
    colors: Mapped[list[dict]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    garment_image_url: Mapped[str] = mapped_column(Text, nullable=False)
    # Segmentation mask (white = garment) used by the try-on model.
    garment_mask_url: Mapped[str | None] = mapped_column(Text)
    # The image as uploaded, kept when background removal replaces `garment_image_url` with a cutout.
    garment_original_url: Mapped[str | None] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    embedding_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Background removal and mask generation (the worker's `process_garment` job).
    processing_status: Mapped[ProcessingStatus] = mapped_column(
        Enum(ProcessingStatus, name="processing_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=ProcessingStatus.idle,
        server_default=ProcessingStatus.idle.value,
    )
    processing_error: Mapped[str | None] = mapped_column(Text)
    processing_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def has_embedding(self) -> bool:
        return self.embedding is not None

    @property
    def on_sale(self) -> bool:
        return self.sale_price_pkr is not None and self.sale_price_pkr < self.price_pkr

    @property
    def current_price_pkr(self) -> int:
        """What the shopper pays: the sale price when on sale, else the regular price."""
        return self.sale_price_pkr if self.on_sale else self.price_pkr
