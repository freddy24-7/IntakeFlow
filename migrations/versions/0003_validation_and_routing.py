"""Stage 3 tables: validations and routing decisions, plus dead-letter columns.

Revision ID: 0003
Revises: 0002
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
    op.add_column(
        "documents", sa.Column("attempts", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column("documents", sa.Column("last_error", sa.String(64), nullable=True))
    op.create_unique_constraint(
        "erp_entries_supplier_name_invoice_number_key",
        "erp_entries",
        ["supplier_name", "invoice_number"],
    )

    op.create_table(
        "validations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("run_key", sa.String(64), nullable=False),
        sa.Column("failures", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("document_id", "run_key"),
    )
    op.create_table(
        "routing_decisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("run_key", sa.String(64), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("field_scores", postgresql.JSONB(), nullable=False),
        sa.Column("reasons", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("document_id", "run_key"),
    )
    for table in ("validations", "routing_decisions"):
        op.create_index(f"ix_{table}_document_id", table, ["document_id"])


def downgrade() -> None:
    op.drop_table("routing_decisions")
    op.drop_table("validations")
    op.drop_constraint(
        "erp_entries_supplier_name_invoice_number_key", "erp_entries", type_="unique"
    )
    op.drop_column("documents", "last_error")
    op.drop_column("documents", "attempts")
