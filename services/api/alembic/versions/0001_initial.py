"""initial schema

Revision ID: 0001
Revises:
Create Date: 2025-01-01 00:00:00

"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIM = 512


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "garments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("sku", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("brand", sa.String(120), nullable=True),
        sa.Column(
            "category",
            sa.Enum("top", "bottom", "dress", "outerwear", "accessory", name="garment_category"),
            nullable=False,
        ),
        sa.Column("color", sa.String(60), nullable=True),
        sa.Column("price_cents", sa.Integer(), nullable=True),
        sa.Column("image_key", sa.String(512), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(EMBEDDING_DIM), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_garments_category_active", "garments", ["category", "is_active"])
    # HNSW index for cosine similarity on garment embeddings (CLIP-style, 512-d).
    op.execute(
        "CREATE INDEX ix_garments_embedding_hnsw ON garments "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )

    op.create_table(
        "sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("kiosk_id", sa.String(120), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
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
        sa.Column(
            "status",
            sa.Enum("queued", "processing", "done", "failed", name="job_status"),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("capture_key", sa.String(512), nullable=False),
        sa.Column("result_key", sa.String(512), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("provider", sa.String(60), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_tryon_jobs_session_id", "tryon_jobs", ["session_id"])
    op.create_index("ix_tryon_jobs_status_created", "tryon_jobs", ["status", "created_at"])


def downgrade() -> None:
    op.drop_table("tryon_jobs")
    op.drop_table("sessions")
    op.drop_table("garments")
    op.execute("DROP TYPE IF EXISTS job_status")
    op.execute("DROP TYPE IF EXISTS garment_category")
