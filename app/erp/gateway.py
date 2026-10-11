"""The one path to the mock ERP (rule 4).

`post_to_erp` is the only place that creates an ERP entry. A test reads the
source tree and fails if a second one appears, and a database trigger refuses
entries for documents that are not approved.
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log as audit
from app.db.models import Document, DocumentStatus, ErpEntry

ERP_ALLOWED_STATUSES = frozenset(
    {DocumentStatus.APPROVED.value, DocumentStatus.AUTO_APPROVED.value}
)


class DocumentNotFoundError(Exception):
    pass


class NotApprovedError(Exception):
    def __init__(self, document_id: uuid.UUID, status: str) -> None:
        super().__init__(f"document {document_id} has status {status!r} and may not reach the ERP")
        self.document_id = document_id
        self.status = status


@dataclass(frozen=True)
class ErpInvoice:
    supplier_name: str
    invoice_number: str
    total: Decimal
    currency: str


async def post_to_erp(
    session: AsyncSession, document_id: uuid.UUID, invoice: ErpInvoice
) -> ErpEntry:
    """Book an approved document. Safe to call twice: the second call returns the first entry."""
    document = await session.get(Document, document_id)
    if document is None:
        raise DocumentNotFoundError(str(document_id))
    if document.status not in ERP_ALLOWED_STATUSES:
        raise NotApprovedError(document_id, document.status)

    existing = (
        await session.execute(select(ErpEntry).where(ErpEntry.document_id == document_id))
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    entry = ErpEntry(
        document_id=document_id,
        supplier_name=invoice.supplier_name,
        invoice_number=invoice.invoice_number,
        total=invoice.total,
        currency=invoice.currency,
    )
    session.add(entry)
    await session.flush()
    await audit.append(
        session,
        step="erp_posted",
        document_id=document_id,
        payload={"erp_entry_id": str(entry.id), "status": document.status},
    )
    return entry
