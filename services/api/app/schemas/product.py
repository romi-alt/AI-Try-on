import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.product import ProcessingStatus, ProductCategory

MAX_SIZES = 20
MAX_COLORS = 12
MAX_URL = 2048
_NO_CONTROL_CHARS = (
    r"^[^\x00-\x1f\x7f]*$"  # no newlines, tabs or other control characters in names and labels
)


class ColorOption(BaseModel):
    name: str = Field(min_length=1, max_length=40, pattern=_NO_CONTROL_CHARS)
    hex: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")


def _check_sizes(sizes: list[str] | None) -> list[str] | None:
    if sizes is None:
        return None
    if len(sizes) > MAX_SIZES:
        raise ValueError(f"at most {MAX_SIZES} sizes")
    for size in sizes:
        if not 1 <= len(size) <= 20 or any(ord(c) < 32 or ord(c) == 127 for c in size):
            raise ValueError("each size must be 1 to 20 characters, with no control characters")
    if len(set(sizes)) != len(sizes):
        raise ValueError("sizes must not repeat")
    return sizes


def _check_url(url: str | None) -> str | None:
    if url is not None and not (
        url.startswith(("http://", "https://")) and len(url) <= MAX_URL and url.isprintable()
    ):
        raise ValueError(f"must be an http(s) address of at most {MAX_URL} characters")
    return url


class ProductBase(BaseModel):
    sku: str | None = Field(default=None, min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200, pattern=_NO_CONTROL_CHARS)
    category: ProductCategory
    price_pkr: int = Field(ge=0, le=2_000_000_000)
    sale_price_pkr: int | None = Field(default=None, ge=0, le=2_000_000_000)
    sizes: list[str] = Field(default_factory=list)
    colors: list[ColorOption] = Field(default_factory=list, max_length=MAX_COLORS)
    stock: int = Field(default=0, ge=0, le=2_000_000_000)
    garment_image_url: str = Field(min_length=1)
    garment_mask_url: str | None = None

    @field_validator("sizes")
    @classmethod
    def _sizes(cls, v):
        return _check_sizes(v)

    @field_validator("garment_image_url", "garment_mask_url")
    @classmethod
    def _urls(cls, v):
        return _check_url(v)

    @model_validator(mode="after")
    def _sale_not_above_price(self):
        if self.sale_price_pkr is not None and self.sale_price_pkr > self.price_pkr:
            raise ValueError("sale_price_pkr cannot exceed price_pkr")
        return self


class ProductCreate(ProductBase):
    pass


class ProductUpdate(BaseModel):
    sku: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=200, pattern=_NO_CONTROL_CHARS)
    category: ProductCategory | None = None
    price_pkr: int | None = Field(default=None, ge=0, le=2_000_000_000)
    sale_price_pkr: int | None = Field(default=None, ge=0, le=2_000_000_000)
    sizes: list[str] | None = None
    colors: list[ColorOption] | None = Field(default=None, max_length=MAX_COLORS)
    stock: int | None = Field(default=None, ge=0, le=2_000_000_000)
    garment_image_url: str | None = Field(default=None, min_length=1)
    garment_mask_url: str | None = None

    @field_validator("sizes")
    @classmethod
    def _sizes(cls, v):
        return _check_sizes(v)

    @field_validator("garment_image_url", "garment_mask_url")
    @classmethod
    def _urls(cls, v):
        return _check_url(v)


class ProductOut(ProductBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    on_sale: bool
    current_price_pkr: int
    garment_original_url: str | None = None
    has_embedding: bool = False
    embedding_updated_at: datetime | None = None
    processing_status: ProcessingStatus = ProcessingStatus.idle
    processing_error: str | None = None
    processing_updated_at: datetime | None = None


class SimilarProductOut(ProductOut):
    # Cosine distance to the reference item; None when no embedding is available and the item is a plain
    # fallback.
    distance: float | None


class AssetJobAccepted(BaseModel):
    job_id: str = Field(description="RQ job id on the assets queue")
    products: int = Field(description="How many products the job covers (0 means the whole catalog)")


class EmbeddingRequest(BaseModel):
    product_ids: list[uuid.UUID] | None = Field(
        default=None, max_length=500, description="Products to embed; omit for the whole catalog"
    )
    only_missing: bool = Field(default=False, description="Skip products that already have an embedding")


class ImportRowResult(BaseModel):
    line: int = Field(description="Line in the file (the header is line 1)")
    action: str = Field(description="create, update or error")
    sku: str | None
    name: str | None
    errors: list[str] = Field(default_factory=list)


class ImportReport(BaseModel):
    dry_run: bool
    applied: bool = Field(
        description="True only when the changes were saved: never after errors or a dry run"
    )
    created: int
    updated: int
    error_count: int
    rows: list[ImportRowResult]
    embedding_job_id: str | None = None
