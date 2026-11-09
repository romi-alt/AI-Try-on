"""share links, staff requests, payment fields, recommended products on try-on jobs

- orders: payment_status / payment_provider / payment_reference (existing orders are `unpaid`: paid at the
  counter)
- share_links: short codes for the mobile page
- staff_requests: "Request Outfit"
- tryon_jobs.recommended_product_ids: which products came from a recommendation

Revision ID: 0005
Revises: 0004
Create Date: 2025-01-05 00:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

payment_status = postgresql.ENUM(
    "unpaid", "pending", "paid", "failed", name="payment_status", create_type=False
)
staff_request_status = postgresql.ENUM(
    "open", "bringing", "done", name="staff_request_status", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    payment_status.create(bind)
    staff_request_status.create(bind)

    op.add_column(
        "orders", sa.Column("payment_status", payment_status, nullable=False, server_default="unpaid")
    )
    op.add_column("orders", sa.Column("payment_provider", sa.String(40)))
    op.add_column("orders", sa.Column("payment_reference", sa.String(120)))

    op.add_column(
        "tryon_jobs",
        sa.Column(
            "recommended_product_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default=sa.text("'{}'::uuid[]"),
        ),
    )

    op.create_table(
        "share_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("short_code", sa.String(16), nullable=False),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("job_id", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("short_code", name="uq_share_links_short_code"),
    )
    op.create_index("ix_share_links_session_id", "share_links", ["session_id"])

    op.create_table(
        "staff_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_name", sa.String(200), nullable=False),
        sa.Column("size", sa.String(20)),
        sa.Column("color", sa.String(40)),
        sa.Column("status", staff_request_status, nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_staff_requests_status_created", "staff_requests", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_staff_requests_status_created", table_name="staff_requests")
    op.drop_table("staff_requests")
    op.drop_index("ix_share_links_session_id", table_name="share_links")
    op.drop_table("share_links")
    op.drop_column("tryon_jobs", "recommended_product_ids")
    op.drop_column("orders", "payment_reference")
    op.drop_column("orders", "payment_provider")
    op.drop_column("orders", "payment_status")
    op.execute("DROP TYPE staff_request_status")
    op.execute("DROP TYPE payment_status")
