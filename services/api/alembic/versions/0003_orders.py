"""orders and order_items (checkout)

An order is the cart as it was at checkout, with names, options and prices copied onto the rows so later
catalog edits or deletions cannot change what was ordered. `idempotency_key` lets a retried checkout find its
order instead of creating a second one.

Revision ID: 0003
Revises: 0002
Create Date: 2025-01-03 00:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sessions.id", ondelete="SET NULL")
        ),
        sa.Column("idempotency_key", postgresql.UUID(as_uuid=True)),
        sa.Column("pickup_code", sa.String(12), nullable=False),
        sa.Column("item_count", sa.Integer, nullable=False),
        sa.Column("subtotal_pkr", sa.BigInteger, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("pickup_code", name="uq_orders_pickup_code"),
        sa.UniqueConstraint("session_id", "idempotency_key", name="uq_orders_session_idempotency_key"),
        sa.CheckConstraint("subtotal_pkr >= 0", name="ck_orders_subtotal_nonneg"),
    )
    op.create_index("ix_orders_created_at", "orders", ["created_at"])

    op.create_table(
        "order_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_name", sa.String(200), nullable=False),
        sa.Column("garment_image_url", sa.Text, nullable=False),
        sa.Column("size", sa.String(20)),
        sa.Column("color", sa.String(40)),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("unit_price_pkr", sa.Integer, nullable=False),
        sa.Column("line_total_pkr", sa.BigInteger, nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_order_items_quantity_positive"),
    )
    op.create_index("ix_order_items_order_id", "order_items", ["order_id"])


def downgrade() -> None:
    op.drop_index("ix_order_items_order_id", table_name="order_items")
    op.drop_table("order_items")
    op.drop_index("ix_orders_created_at", table_name="orders")
    op.drop_table("orders")
