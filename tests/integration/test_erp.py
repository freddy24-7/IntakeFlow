"""Rule 4: only approved documents reach the mock ERP, through one function."""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log as audit
from app.db.models import AuditRecord, Document, DocumentStatus
from app.erp import gateway
from app.erp.gateway import ErpInvoice, NotApprovedError, post_to_erp

INVOICE = ErpInvoice(
    supplier_name="Voorbeeld B.V.",
    invoice_number="F2026-0001",
    total=Decimal("1234.56"),
    currency="EUR",
)
NOT_APPROVED = [s for s in DocumentStatus if s.value not in gateway.ERP_ALLOWED_STATUSES]


async def _document(session: AsyncSession, status: DocumentStatus) -> Document:
    document = Document(filename="doc-0001.pdf", content_sha256="0" * 64, status=status.value)
    session.add(document)
    await session.flush()
    return document


async def _erp_count(session: AsyncSession) -> int:
    # Raw SQL on purpose: only the gateway may use the ERP model (see tests/architecture.py).
    return (await session.execute(text("SELECT count(*) FROM erp_entries"))).scalar_one()  # type: ignore[no-any-return]


def test_only_the_two_approved_statuses_are_allowed() -> None:
    assert frozenset({"approved", "auto_approved"}) == gateway.ERP_ALLOWED_STATUSES


@pytest.mark.parametrize("status", [DocumentStatus.APPROVED, DocumentStatus.AUTO_APPROVED])
async def test_approved_document_is_booked_and_audited(
    session: AsyncSession, status: DocumentStatus
) -> None:
    document = await _document(session, status)

    entry = await post_to_erp(session, document.id, INVOICE)

    assert entry.document_id == document.id
    assert entry.total == Decimal("1234.56")
    assert await _erp_count(session) == 1
    assert await audit.step_already_ran(session, document.id, "erp_posted")


@pytest.mark.parametrize("status", NOT_APPROVED)
async def test_unapproved_document_is_refused(
    session: AsyncSession, status: DocumentStatus
) -> None:
    document = await _document(session, status)

    with pytest.raises(NotApprovedError) as error:
        await post_to_erp(session, document.id, INVOICE)

    assert error.value.status == status.value
    assert await _erp_count(session) == 0
    assert not await audit.step_already_ran(session, document.id, "erp_posted")


async def test_posting_twice_books_once(session: AsyncSession) -> None:
    document = await _document(session, DocumentStatus.APPROVED)

    first = await post_to_erp(session, document.id, INVOICE)
    second = await post_to_erp(session, document.id, INVOICE)

    assert second.id == first.id
    assert await _erp_count(session) == 1
    audit_records = await session.execute(
        select(func.count()).select_from(AuditRecord).where(AuditRecord.step == "erp_posted")
    )
    assert audit_records.scalar_one() == 1


async def test_unknown_document_is_refused(session: AsyncSession) -> None:
    with pytest.raises(gateway.DocumentNotFoundError):
        await post_to_erp(session, uuid.uuid4(), INVOICE)


async def test_database_refuses_an_insert_that_goes_around_the_gateway(
    session: AsyncSession,
) -> None:
    """Built wrongly on purpose: write to the ERP table directly for a document in review."""
    document = await _document(session, DocumentStatus.IN_REVIEW)

    with pytest.raises(DBAPIError, match="not approved for the ERP"):
        async with session.begin_nested():
            await session.execute(
                text(
                    "INSERT INTO erp_entries (id, document_id, supplier_name, invoice_number,"
                    " total, currency) VALUES (:id, :document_id, 'x', 'y', 1, 'EUR')"
                ),
                {"id": uuid.uuid4(), "document_id": document.id},
            )

    assert await _erp_count(session) == 0
