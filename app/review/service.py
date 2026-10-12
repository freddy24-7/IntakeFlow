"""Human review (PRD F6): approve, correct or reject a document.

Rule 5: a reviewer's corrections are stored in their own record next to the
model's extraction. The extraction itself is never changed.

The reviewer is in charge. Corrected values are validated again and the
failures are shown and recorded, but they do not block an approval.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import normalise
from app.agents.schema import FIELD_KINDS, ExtractedInvoice
from app.audit import log as audit
from app.config import Settings
from app.db.models import Document, DocumentStatus, Extraction, Review, RoutingDecision
from app.erp.gateway import DuplicateInvoiceError, ErpInvoice, post_to_erp
from app.validation import rules
from app.workflow.routing_steps import validation_context

STEP_REVIEWED = "reviewed"
ACTION_APPROVED, ACTION_REJECTED = "approved", "rejected"
REQUIRED_FOR_BOOKING = ("supplier_name", "invoice_number", "total", "currency")


class ReviewError(Exception):
    """The review cannot be carried out. The message is shown to the reviewer."""


@dataclass
class ReviewCase:
    """Everything the review page shows for one document."""

    document: Document
    reasons: list[str] = field(default_factory=list)
    extraction_id: uuid.UUID | None = None
    run_key: str | None = None
    invoice: ExtractedInvoice | None = None


@dataclass
class Corrected:
    invoice: ExtractedInvoice
    corrections: dict[str, str | None]  # only the fields that changed
    errors: dict[str, str]  # fields whose input could not be read


async def load_case(session: AsyncSession, document_id: uuid.UUID) -> ReviewCase:
    document = await session.get(Document, document_id)
    if document is None:
        raise ReviewError("Dit document bestaat niet.")
    case = ReviewCase(document=document)
    decision = (
        await session.execute(
            select(RoutingDecision)
            .where(RoutingDecision.document_id == document_id)
            .order_by(RoutingDecision.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if decision is None:
        return case
    extraction = (
        await session.execute(
            select(Extraction).where(
                Extraction.document_id == document_id, Extraction.run_key == decision.run_key
            )
        )
    ).scalar_one()
    case.reasons = list(decision.reasons)
    case.extraction_id = extraction.id
    case.run_key = extraction.run_key
    case.invoice = ExtractedInvoice.model_validate(extraction.data)
    return case


def apply_corrections(invoice: ExtractedInvoice, submitted: Mapping[str, str]) -> Corrected:
    """Compare the submitted form with the extraction. Returns a corrected copy.

    Input goes through the same normalisation as the model's output, so a
    reviewer may type 1.234,56 or 15-10-2026. Flags are cleared on the copy:
    a person has now looked at every field.
    """
    corrected = invoice.model_copy(deep=True)
    corrections: dict[str, str | None] = {}
    errors: dict[str, str] = {}
    for name, kind in FIELD_KINDS.items():
        raw = submitted.get(name, "").strip()
        value = normalise.canonical(kind, raw) if raw else None
        if raw and value is None:
            errors[name] = "Deze waarde kan niet worden gelezen."
            continue
        if value != invoice.fields[name].value:
            corrections[name] = value
        corrected.fields[name].value = value
        corrected.fields[name].flags = []
    return Corrected(corrected, corrections, errors)


async def _open_case(session: AsyncSession, document_id: uuid.UUID) -> ReviewCase:
    case = await load_case(session, document_id)
    if case.document.status != DocumentStatus.IN_REVIEW.value:
        raise ReviewError("Dit document wacht niet (meer) op beoordeling.")
    return case


async def check(
    session: AsyncSession,
    document_id: uuid.UUID,
    submitted: Mapping[str, str],
    *,
    settings: Settings,
    today: date,
) -> tuple[Corrected, list[str]]:
    """Validate the values as the reviewer has them now, without storing anything."""
    case = await _open_case(session, document_id)
    if case.invoice is None or case.run_key is None:
        raise ReviewError("Dit document heeft geen factuurgegevens.")
    corrected = apply_corrections(case.invoice, submitted)
    context = await validation_context(
        session, case.document, corrected.invoice, case.run_key, settings=settings, today=today
    )
    return corrected, rules.validate(corrected.invoice, context)


async def approve(
    session: AsyncSession,
    document_id: uuid.UUID,
    submitted: Mapping[str, str],
    *,
    role: str,
    settings: Settings,
    today: date,
) -> Review:
    """Approve with the submitted values and book the document. The caller commits."""
    corrected, failures = await check(
        session, document_id, submitted, settings=settings, today=today
    )
    if corrected.errors:
        raise ReviewError("Niet alle velden zijn leesbaar ingevuld.")
    values = {name: item.value for name, item in corrected.invoice.fields.items()}
    if any(values[name] is None for name in REQUIRED_FOR_BOOKING):
        raise ReviewError("Leverancier, factuurnummer, totaal en valuta zijn nodig om te boeken.")

    case = await load_case(session, document_id)
    review = Review(
        document_id=document_id,
        extraction_id=case.extraction_id,
        reviewer_role=role,
        action=ACTION_APPROVED,
        corrections=corrected.corrections,
        unchanged=not corrected.corrections,
        failures_at_approval=failures,
    )
    session.add(review)
    case.document.status = DocumentStatus.APPROVED.value
    await session.flush()
    try:
        await post_to_erp(
            session,
            document_id,
            ErpInvoice(
                supplier_name=str(values["supplier_name"]),
                invoice_number=str(values["invoice_number"]),
                total=Decimal(str(values["total"])),
                currency=str(values["currency"]),
            ),
        )
    except DuplicateInvoiceError as error:
        raise ReviewError(
            "Deze factuur (leverancier en factuurnummer) is al geboekt. Wijs het document af."
        ) from error
    # Rule 8: which fields were corrected, never the values.
    await audit.append(
        session,
        step=STEP_REVIEWED,
        document_id=document_id,
        payload={
            "action": ACTION_APPROVED,
            "role": role,
            "corrected_fields": [*sorted(corrected.corrections)],
            "failures": [*failures],
        },
    )
    return review


async def reject(
    session: AsyncSession, document_id: uuid.UUID, *, role: str, reason: str
) -> Review:
    """Reject the document. Nothing reaches the ERP. The caller commits."""
    case = await _open_case(session, document_id)
    if not reason.strip():
        raise ReviewError("Geef een reden voor de afwijzing.")
    review = Review(
        document_id=document_id,
        extraction_id=case.extraction_id,
        reviewer_role=role,
        action=ACTION_REJECTED,
        corrections={},
        unchanged=True,
        failures_at_approval=[],
        reason=reason.strip()[:500],
    )
    session.add(review)
    case.document.status = DocumentStatus.REJECTED.value
    # The reason is free text and may quote the document, so it stays out of the audit log.
    await audit.append(
        session,
        step=STEP_REVIEWED,
        document_id=document_id,
        payload={"action": ACTION_REJECTED, "role": role},
    )
    return review
