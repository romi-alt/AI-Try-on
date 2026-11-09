"""products, carts, and reshaped sessions / tryon_jobs

Replaces the scaffold's garments/sessions/tryon_jobs tables with the shopping
schema: products (PKR pricing, pgvector embedding), sessions with consent,
multi-product tryon_jobs with progress, and carts / cart_items.

DESTRUCTIVE for dev data: the old tables held only scaffold seed data and have
no production counterpart, so they are dropped rather than migrated. The
downgrade restores the old (empty) tables.

Revision ID: 0002
Revises: 0001
Create Date: 2025-01-02 00:00:00

"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIM = 512

product_category = postgresql.ENUM(
    "top", "bottom", "dress", "shoes", "bag", "accessory", name="product_category", create_type=False
)
job_status = postgresql.ENUM("queued", "processing", "done", "failed", name="job_status", create_type=False)
legacy_garment_category = postgresql.ENUM(
    "top", "bottom", "dress", "outerwear", "accessory", name="garment_category", create_type=False
)


def _now() -> sa.sql.elements.TextClause:
    return sa.text("now()")


def upgrade() -> None:
    # --- drop the scaffold schema (children first) -------------------------------------------
    op.drop_table("tryon_jobs")
    op.drop_table("sessions")
    op.drop_table("garments")
    op.execute("DROP TYPE job_status")
    op.execute("DROP TYPE garment_category")

    bind = op.get_bind()
    product_category.create(bind)
    job_status.create(bind)

    # --- products ----------------------------------------------------------------------------
    op.create_table(
        "products",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("category", product_category, nullable=False),
        sa.Column("price_pkr", sa.Integer(), nullable=False),
        sa.Column("sale_price_pkr", sa.Integer(), nullable=True),
        sa.Column("sizes", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("colors", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("stock", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("garment_image_url", sa.Text(), nullable=False),
        sa.Column("garment_mask_url", sa.Text(), nullable=True),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(EMBEDDING_DIM), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
        sa.CheckConstraint("price_pkr >= 0", name="ck_products_price_nonneg"),
        sa.CheckConstraint(
            "sale_price_pkr IS NULL OR (sale_price_pkr >= 0 AND sale_price_pkr <= price_pkr)",
            name="ck_products_sale_price_valid",
        ),
        sa.CheckConstraint("stock >= 0", name="ck_products_stock_nonneg"),
    )
    op.create_index("ix_products_category", "products", ["category"])
    op.create_index(
        "ix_products_embedding_hnsw",
        "products",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    # --- sessions ----------------------------------------------------------------------------
    op.create_table(
        "sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
        sa.Column("consent_given", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    # --- tryon_jobs --------------------------------------------------------------------------
    op.create_table(
        "tryon_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("product_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=False),
        sa.Column("status", job_status, nullable=False, server_default="queued"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("person_image_key", sa.String(512), nullable=False),
        sa.Column("result_url", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
        sa.CheckConstraint("progress BETWEEN 0 AND 100", name="ck_tryon_jobs_progress_range"),
        sa.CheckConstraint("cardinality(product_ids) >= 1", name="ck_tryon_jobs_has_products"),
    )
    op.create_index("ix_tryon_jobs_session_id", "tryon_jobs", ["session_id"])
    op.create_index("ix_tryon_jobs_status_created", "tryon_jobs", ["status", "created_at"])

    # --- carts / cart_items ------------------------------------------------------------------
    op.create_table(
        "carts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
    )
    op.create_table(
        "cart_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "cart_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("carts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("size", sa.String(20), nullable=True),
        sa.Column("color", sa.String(40), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
        sa.CheckConstraint("quantity > 0", name="ck_cart_items_quantity_positive"),
    )
    op.create_index("ix_cart_items_cart_id", "cart_items", ["cart_id"])


def downgrade() -> None:
    op.drop_table("cart_items")
    op.drop_table("carts")
    op.drop_table("tryon_jobs")
    op.drop_table("sessions")
    op.drop_table("products")
    op.execute("DROP TYPE job_status")
    op.execute("DROP TYPE product_category")

    # --- restore the 0001 schema (empty) -----------------------------------------------------
    bind = op.get_bind()
    legacy_garment_category.create(bind)
    job_status.create(bind)

    op.create_table(
        "garments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("sku", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("brand", sa.String(120), nullable=True),
        sa.Column("category", legacy_garment_category, nullable=False),
        sa.Column("color", sa.String(60), nullable=True),
        sa.Column("price_cents", sa.Integer(), nullable=True),
        sa.Column("image_key", sa.String(512), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(EMBEDDING_DIM), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
    )
    op.create_index("ix_garments_category_active", "garments", ["category", "is_active"])
    op.execute(
        "CREATE INDEX ix_garments_embedding_hnsw ON garments "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )

    op.create_table(
        "sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("kiosk_id", sa.String(120), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_sessions_started_at", "sessions", ["started_at"])

    op.create_table(
        "tryon_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "garment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("garments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", job_status, nullable=False, server_default="queued"),
        sa.Column("capture_key", sa.String(512), nullable=False),
        sa.Column("result_key", sa.String(512), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("provider", sa.String(60), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
    )
    op.create_index("ix_tryon_jobs_session_id", "tryon_jobs", ["session_id"])
    op.create_index("ix_tryon_jobs_status_created", "tryon_jobs", ["status", "created_at"])
