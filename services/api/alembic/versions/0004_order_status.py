"""order status: placed, collected, cancelled

Existing orders are all still waiting, so they become `placed`. `status_changed_at` records when an order was
last collected or cancelled.

Revision ID: 0004
Revises: 0003
Create Date: 2025-01-04 00:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

order_status = postgresql.ENUM("placed", "collected", "cancelled", name="order_status", create_type=False)


def upgrade() -> None:
    order_status.create(op.get_bind())
    op.add_column("orders", sa.Column("status", order_status, nullable=False, server_default="placed"))
    op.add_column("orders", sa.Column("status_changed_at", sa.DateTime(timezone=True)))
    op.create_index("ix_orders_status_created_at", "orders", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_orders_status_created_at", table_name="orders")
    op.drop_column("orders", "status_changed_at")
    op.drop_column("orders", "status")
    op.execute("DROP TYPE order_status")
