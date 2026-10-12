"""The stage 3 steps: validate, decide, apply the decision.

Validation and the decision are stored per extraction run, so the evaluation
can compare the three extraction variants on the same documents. Applying the
decision (document status and the ERP booking) happens once per document, for
the variant the pipeline is configured to use.
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.schema import ExtractedInvoice
from app.audit import log as audit
from app.config import Settings
from app.db.models import (
    Classification,
    Document,
    DocumentStatus,
    Extraction,
    PurchaseOrder,
    RoutingDecision,
    Validation,
)
from app.erp.gateway import DuplicateInvoiceError, ErpInvoice, post_to_erp
from app.validation import rules, scoring
from app.workflow import steps
from app.workflow.steps import Services

STEP_APPLIED = "decision_applied"
STEP_NON_INVOICE = "routed_non_invoice"
REASON_NOT_AN_INVOICE = "not_an_invoice"
REASON_ALREADY_IN_ERP = "already_in_erp"


async def _extraction(
    session: AsyncSession, document_id: uuid.UUID, run_key: str
) -> ExtractedInvoice:
    row = await session.execute(
        select(Extraction.data).where(
            Extraction.document_id == document_id, Extraction.run_key == run_key
        )
    )
    return ExtractedInvoice.model_validate(row.scalar_one())


async def _is_duplicate(
    session: AsyncSession, document: Document, invoice: ExtractedInvoice, run_key: str
) -> bool:
    """Does an earlier document have the same supplier and invoice number?

    "Earlier" is by upload time, then file name, so of two copies exactly one
    is the duplicate, whichever is processed first.
    """
    supplier = invoice.fields["supplier_name"].value
    number = invoice.fields["invoice_number"].value
    if supplier is None or number is None:
        return False
    fields = Extraction.data["fields"]
    earlier = await session.execute(
        select(Extraction.id)
        .join(Document, Document.id == Extraction.document_id)
        .where(
            Extraction.run_key == run_key,
            Extraction.document_id != document.id,
            fields["supplier_name"]["value"].astext == supplier,
            fields["invoice_number"]["value"].astext == number,
            tuple_(Document.created_at, Document.filename)
            < tuple_(document.created_at, document.filename),
        )
        .limit(1)
    )
    return earlier.first() is not None


async def validate_invoice(
    session: AsyncSession,
    services: Services,
    document_id: uuid.UUID,
    variant: str,
    *,
    settings: Settings,
    today: date,
) -> None:
    run_key = steps.extract_run_key(services, variant)
    step = f"validated:{run_key}"
    if await audit.step_already_ran(session, document_id, step):
        return
    document = await session.get_one(Document, document_id)
    invoice = await _extraction(session, document_id, run_key)

    order_info = None
    reference = invoice.fields["purchase_order_reference"].value
    if reference is not None:
        order = await session.get(PurchaseOrder, reference)
        if order is not None:
            order_info = rules.PurchaseOrderInfo(
                order.supplier_name, order.supplier_vat_number, order.amount
            )
    context = rules.ValidationContext(
        today=today,
        purchase_order=order_info,
        is_duplicate=await _is_duplicate(session, document, invoice, run_key),
        po_tolerance=Decimal(str(settings.po_amount_tolerance)),
    )
    failures = rules.validate(invoice, context)
    session.add(Validation(document_id=document_id, run_key=run_key, failures=failures))
    await audit.append(
        session, step=step, document_id=document_id, payload={"failures": list(failures)}
    )


async def decide_routing(
    session: AsyncSession,
    services: Services,
    document_id: uuid.UUID,
    variant: str,
    *,
    settings: Settings,
) -> str:
    """Store and return the decision for this extraction run."""
    run_key = steps.extract_run_key(services, variant)
    step = f"routed:{run_key}"
    if await audit.step_already_ran(session, document_id, step):
        stored = await session.execute(
            select(RoutingDecision.decision).where(
                RoutingDecision.document_id == document_id, RoutingDecision.run_key == run_key
            )
        )
        return stored.scalar_one()

    invoice = await _extraction(session, document_id, run_key)
    failures = (
        await session.execute(
            select(Validation.failures).where(
                Validation.document_id == document_id, Validation.run_key == run_key
            )
        )
    ).scalar_one()
    classification_confidence = (
        await session.execute(
            select(Classification.confidence).where(
                Classification.document_id == document_id,
                Classification.run_key == steps.classify_run_key(services),
            )
        )
    ).scalar_one()

    field_scores = scoring.field_scores(
        invoice, default_confidence=settings.score_default_confidence
    )
    score = scoring.aggregate(field_scores, settings.score_aggregate)
    decision = scoring.decide(
        failures=failures,
        score=score,
        threshold=settings.auto_approve_threshold,
        classification_confidence=classification_confidence,
        classification_threshold=settings.classification_threshold,
    )
    session.add(
        RoutingDecision(
            document_id=document_id,
            run_key=run_key,
            decision=decision.decision,
            score=score,
            threshold=settings.auto_approve_threshold,
            field_scores=field_scores,
            reasons=decision.reasons,
        )
    )
    await audit.append(
        session,
        step=step,
        document_id=document_id,
        payload={
            "decision": decision.decision,
            "score": f"{score:.3f}",
            "threshold": f"{settings.auto_approve_threshold:.3f}",
            "reasons": list(decision.reasons),
        },
    )
    return decision.decision


async def apply_decision(
    session: AsyncSession, services: Services, document_id: uuid.UUID, variant: str
) -> None:
    """Set the document's status from the stored decision and book it when auto-approved.

    This is the only place where a document becomes auto-approved, and it only
    acts on a decision that `scoring.decide` made (rule 3).
    """
    if await audit.step_already_ran(session, document_id, STEP_APPLIED):
        return
    run_key = steps.extract_run_key(services, variant)
    document = await session.get_one(Document, document_id)
    decision = (
        await session.execute(
            select(RoutingDecision).where(
                RoutingDecision.document_id == document_id, RoutingDecision.run_key == run_key
            )
        )
    ).scalar_one()

    status = DocumentStatus.IN_REVIEW
    reasons = list(decision.reasons)
    if decision.decision == scoring.AUTO_APPROVE:
        invoice = await _extraction(session, document_id, run_key)
        values = {name: field.value for name, field in invoice.fields.items()}
        document.status = DocumentStatus.AUTO_APPROVED.value
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
            status = DocumentStatus.AUTO_APPROVED
        except DuplicateInvoiceError:
            reasons.append(REASON_ALREADY_IN_ERP)
    document.status = status.value
    await audit.append(
        session,
        step=STEP_APPLIED,
        document_id=document_id,
        payload={"status": status.value, "reasons": [*reasons]},
    )


async def route_non_invoice(session: AsyncSession, document_id: uuid.UUID, label: str) -> None:
    """Documents without an invoice extraction. Unknown mail goes to a person.
    Contracts wait for indexing, which stage 5 adds."""
    if await audit.step_already_ran(session, document_id, STEP_NON_INVOICE):
        return
    document = await session.get_one(Document, document_id)
    if label != "contract":
        document.status = DocumentStatus.IN_REVIEW.value
    await audit.append(
        session,
        step=STEP_NON_INVOICE,
        document_id=document_id,
        payload={"label": label, "status": document.status},
    )
