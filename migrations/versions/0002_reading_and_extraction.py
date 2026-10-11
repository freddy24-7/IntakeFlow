"""Stage 2 tables: readings, classifications, extractions, usage records.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _id_and_document() -> list[sa.Column[Any]]:
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("documents.id"), nullable=False),
    ]


def _created_at() -> sa.Column[Any]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade() -> None:
    op.add_column("documents", sa.Column("storage_key", sa.String(255), nullable=True))
    op.add_column("documents", sa.Column("size_bytes", sa.Integer(), nullable=True))

    op.create_table(
        "readings",
        *_id_and_document(),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=False),
        _created_at(),
        sa.UniqueConstraint("document_id", "kind"),
    )
    op.create_table(
        "classifications",
        *_id_and_document(),
        sa.Column("run_key", sa.String(64), nullable=False),
        sa.Column("label", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        _created_at(),
        sa.UniqueConstraint("document_id", "run_key"),
    )
    op.create_table(
        "extractions",
        *_id_and_document(),
        sa.Column("run_key", sa.String(64), nullable=False),
        sa.Column("variant", sa.String(16), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        _created_at(),
        sa.UniqueConstraint("document_id", "run_key"),
    )
    op.create_table(
        "usage_records",
        *_id_and_document(),
        sa.Column("step", sa.String(64), nullable=False),
        sa.Column("service", sa.String(32), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("pages", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        _created_at(),
    )
    for table in ("readings", "classifications", "extractions", "usage_records"):
        op.create_index(f"ix_{table}_document_id", table, ["document_id"])


def downgrade() -> None:
    for table in ("usage_records", "extractions", "classifications", "readings"):
        op.drop_table(table)
    op.drop_column("documents", "size_bytes")
    op.drop_column("documents", "storage_key")
