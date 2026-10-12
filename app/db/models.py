"""Database tables. Changes here need a matching Alembic migration."""

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DocumentStatus(StrEnum):
    RECEIVED = "received"
    PROCESSING = "processing"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    AUTO_APPROVED = "auto_approved"
    REJECTED = "rejected"
    FAILED = "failed"


class Document(Base):
    """One uploaded file. Its id doubles as the correlation id in logs (rule 8)."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    filename: Mapped[str] = mapped_column(String(255))
    content_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default=DocumentStatus.RECEIVED.value)
    document_type: Mapped[str | None] = mapped_column(String(32))
    storage_key: Mapped[str | None] = mapped_column(String(255))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    # "upload" for documents that came in through the application, "evaluation" for
    # documents registered by the evaluation scripts. The dashboard shows uploads only.
    origin: Mapped[str] = mapped_column(String(16), default="upload", server_default="upload")
    # Dead-letter bookkeeping: how often processing failed, and the kind of the last error.
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PurchaseOrder(Base):
    """Purchase order data that invoices are cross-checked against."""

    __tablename__ = "purchase_orders"

    po_number: Mapped[str] = mapped_column(String(32), primary_key=True)
    supplier_name: Mapped[str] = mapped_column(String(255))
    supplier_vat_number: Mapped[str] = mapped_column(String(20))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3))


class AuditRecord(Base):
    """Append-only, hash-chained log (rule 7). Written only through app.audit.log."""

    __tablename__ = "audit_log"

    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"), index=True)
    step: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    prev_hash: Mapped[str] = mapped_column(String(64))
    record_hash: Mapped[str] = mapped_column(String(64), unique=True)


class ErpEntry(Base):
    """The mock ERP. Written only through app.erp.gateway (rule 4)."""

    __tablename__ = "erp_entries"
    # A second booking of the same supplier invoice is refused by the database.
    __table_args__ = (UniqueConstraint("supplier_name", "invoice_number"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), unique=True)
    supplier_name: Mapped[str] = mapped_column(String(255))
    invoice_number: Mapped[str] = mapped_column(String(64))
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3))
    booked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Reading(Base):
    """What Document Intelligence returned. Kept whole for debugging and comparison (PRD F3)."""

    __tablename__ = "readings"
    __table_args__ = (UniqueConstraint("document_id", "kind"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # "text" or "invoice_fields"
    page_count: Mapped[int] = mapped_column(Integer)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Classification(Base):
    __tablename__ = "classifications"
    __table_args__ = (UniqueConstraint("document_id", "run_key"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), index=True)
    run_key: Mapped[str] = mapped_column(String(64))  # prompt version and model
    label: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Extraction(Base):
    """Model output. Never changed after it is written: a reviewer's corrections
    are stored next to it (rule 5)."""

    __tablename__ = "extractions"
    __table_args__ = (UniqueConstraint("document_id", "run_key"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), index=True)
    run_key: Mapped[str] = mapped_column(String(64))  # variant, prompt version and model
    variant: Mapped[str] = mapped_column(String(16))  # "combined", "llm_only" or "di_only"
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UsageRecord(Base):
    """One billable call, for the cost and latency report. No document content (rule 8)."""

    __tablename__ = "usage_records"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), index=True)
    step: Mapped[str] = mapped_column(String(64))
    service: Mapped[str] = mapped_column(String(32))  # "document_intelligence" or "chat"
    model: Mapped[str] = mapped_column(String(64))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    pages: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Validation(Base):
    """Outcome of the deterministic checks for one extraction."""

    __tablename__ = "validations"
    __table_args__ = (UniqueConstraint("document_id", "run_key"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), index=True)
    run_key: Mapped[str] = mapped_column(String(64))
    failures: Mapped[list[str]] = mapped_column(JSONB)  # names of the checks that failed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RoutingDecision(Base):
    """Auto-approve or review, with the score, the threshold used and every reason."""

    __tablename__ = "routing_decisions"
    __table_args__ = (UniqueConstraint("document_id", "run_key"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), index=True)
    run_key: Mapped[str] = mapped_column(String(64))
    decision: Mapped[str] = mapped_column(String(16))  # "auto_approve" or "review"
    score: Mapped[float] = mapped_column(Float)
    threshold: Mapped[float] = mapped_column(Float)
    field_scores: Mapped[dict[str, float]] = mapped_column(JSONB)
    reasons: Mapped[list[str]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Review(Base):
    """A reviewer's verdict. Corrections are stored here, next to the model's
    extraction and never over it (rule 5), so "approved unchanged" is a lookup."""

    __tablename__ = "reviews"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), unique=True)
    extraction_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("extractions.id"))
    reviewer_role: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(16))  # "approved" or "rejected"
    # Only the fields the reviewer changed: name -> corrected canonical value.
    corrections: Mapped[dict[str, Any]] = mapped_column(JSONB)
    unchanged: Mapped[bool] = mapped_column(Boolean)
    # Checks that still failed on the corrected values when the reviewer approved.
    failures_at_approval: Mapped[list[str]] = mapped_column(JSONB)
    reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
