"""Initial tables: documents, purchase orders, audit log, mock ERP.

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("document_type", sa.String(32), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "purchase_orders",
        sa.Column("po_number", sa.String(32), primary_key=True),
        sa.Column("supplier_name", sa.String(255), nullable=False),
        sa.Column("supplier_vat_number", sa.String(20), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
    )
    op.create_table(
        "audit_log",
        sa.Column("seq", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("documents.id"), nullable=True),
        sa.Column("step", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("prev_hash", sa.String(64), nullable=False),
        sa.Column("record_hash", sa.String(64), nullable=False, unique=True),
    )
    op.create_index("ix_audit_log_document_id", "audit_log", ["document_id"])
    op.create_table(
        "erp_entries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "document_id", sa.Uuid(), sa.ForeignKey("documents.id"), nullable=False, unique=True
        ),
        sa.Column("supplier_name", sa.String(255), nullable=False),
        sa.Column("invoice_number", sa.String(64), nullable=False),
        sa.Column("total", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column(
            "booked_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    # Rule 7: the audit log is append-only. The application has no update or
    # delete path, and the database refuses both as a second line of defence.
    op.execute(
        """
        CREATE FUNCTION audit_log_is_append_only() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log is append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_log_no_update_or_delete
        BEFORE UPDATE OR DELETE ON audit_log
        FOR EACH ROW EXECUTE FUNCTION audit_log_is_append_only()
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_log_no_truncate
        BEFORE TRUNCATE ON audit_log
        FOR EACH STATEMENT EXECUTE FUNCTION audit_log_is_append_only()
        """
    )

    # Rule 4: only approved documents reach the ERP. app.erp.gateway checks this
    # first. The trigger catches any code that goes around the gateway.
    op.execute(
        """
        CREATE FUNCTION erp_entry_requires_approval() RETURNS trigger AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM documents
                WHERE id = NEW.document_id AND status IN ('approved', 'auto_approved')
            ) THEN
                RAISE EXCEPTION 'document % is not approved for the ERP', NEW.document_id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER erp_entries_require_approval
        BEFORE INSERT ON erp_entries
        FOR EACH ROW EXECUTE FUNCTION erp_entry_requires_approval()
        """
    )


def downgrade() -> None:
    op.drop_table("erp_entries")
    op.drop_table("audit_log")
    op.drop_table("purchase_orders")
    op.drop_table("documents")
    op.execute("DROP FUNCTION erp_entry_requires_approval()")
    op.execute("DROP FUNCTION audit_log_is_append_only()")
