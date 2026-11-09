"""products: sku, original image, processing status, embedding timestamp

Revision ID: 0006
Revises: 0005
Create Date: 2025-01-06 00:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

processing_status = postgresql.ENUM(
    "idle", "queued", "processing", "done", "failed", name="processing_status", create_type=False
)


def upgrade() -> None:
    processing_status.create(op.get_bind())
    op.add_column("products", sa.Column("sku", sa.String(64)))
    op.create_unique_constraint("uq_products_sku", "products", ["sku"])
    op.add_column("products", sa.Column("garment_original_url", sa.Text))
    op.add_column("products", sa.Column("embedding_updated_at", sa.DateTime(timezone=True)))
    op.add_column(
        "products", sa.Column("processing_status", processing_status, nullable=False, server_default="idle")
    )
    op.add_column("products", sa.Column("processing_error", sa.Text))
    op.add_column("products", sa.Column("processing_updated_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("products", "processing_updated_at")
    op.drop_column("products", "processing_error")
    op.drop_column("products", "processing_status")
    op.drop_column("products", "embedding_updated_at")
    op.drop_column("products", "garment_original_url")
    op.drop_constraint("uq_products_sku", "products", type_="unique")
    op.drop_column("products", "sku")
    op.execute("DROP TYPE processing_status")
