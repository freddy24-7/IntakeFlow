"""Stage 4: reviews, and where a document came from.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("origin", sa.String(16), server_default="upload", nullable=False),
    )
    # Documents registered by the evaluation scripts carry the run name as a folder.
    op.execute("UPDATE documents SET origin = 'evaluation' WHERE filename LIKE '%/%'")

    op.create_table(
        "reviews",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "document_id", sa.Uuid(), sa.ForeignKey("documents.id"), nullable=False, unique=True
        ),
        sa.Column("extraction_id", sa.Uuid(), sa.ForeignKey("extractions.id"), nullable=True),
        sa.Column("reviewer_role", sa.String(32), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("corrections", postgresql.JSONB(), nullable=False),
        sa.Column("unchanged", sa.Boolean(), nullable=False),
        sa.Column("failures_at_approval", postgresql.JSONB(), nullable=False),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("reviews")
    op.drop_column("documents", "origin")
