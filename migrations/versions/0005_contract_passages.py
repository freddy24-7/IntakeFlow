"""Stage 5: clauses of indexed contracts.

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "contract_passages",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("index_name", sa.String(64), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("clause_number", sa.Integer(), nullable=False),
        sa.Column("heading", sa.String(255), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
    )
    op.create_index("ix_contract_passages_document_id", "contract_passages", ["document_id"])


def downgrade() -> None:
    op.drop_table("contract_passages")
