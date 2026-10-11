"""The stage 2 steps with fakes: output lands in the database, and a step that ran is skipped."""

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents import extract
from app.agents.schema import (
    FIELD_KINDS,
    FLAG_DI_DISAGREES,
    ClassificationAnswer,
    ExtractedInvoice,
    LlmField,
    LlmInvoice,
)
from app.audit import log as audit
from app.db.models import (
    AuditRecord,
    Classification,
    Document,
    DocumentStatus,
    Extraction,
    Reading,
    UsageRecord,
)
from app.inference.fakes import FakeChatModel
from app.reading.fakes import FakeDocumentReader, content_key
from app.reading.interfaces import PageText, ReadField, ReadResult
from app.storage.local import MemoryStorage
from app.workflow import steps
from app.workflow.ingest import ingest
from app.workflow.runner import process_document
from app.workflow.steps import Services

PDF = b"%PDF-1.4 synthetic invoice"
TEXT = ReadResult(pages=[PageText(1, "FACTUUR F2026-0001 Totaal 1.234,56")])
DI_FIELDS = [
    ReadField("InvoiceId", "F2026-0001", 0.97, 1),
    ReadField("InvoiceTotal", "1234.56", 0.9, 1),
]


def _llm_invoice(invoice_number: str = "F2026-0001") -> LlmInvoice:
    empty = LlmField(value=None, page=None, source_text=None)
    fields = {name: empty for name in FIELD_KINDS}
    fields["invoice_number"] = LlmField(value=invoice_number, page=1, source_text=invoice_number)
    fields["total"] = LlmField(value="1234.56", page=1, source_text="1.234,56")
    return LlmInvoice(**fields, line_items=[])


def _services(label: str = "invoice", invoice_number: str = "F2026-0001") -> Services:
    storage = MemoryStorage()
    reader = FakeDocumentReader(
        texts={content_key(PDF): TEXT}, invoice_fields={content_key(PDF): DI_FIELDS}
    )
    classifier = FakeChatModel(
        answers={ClassificationAnswer: ClassificationAnswer(label=label, confidence=0.93)},
        model="fake-mini",
    )
    extractor = FakeChatModel(answers={LlmInvoice: _llm_invoice(invoice_number)}, model="fake-big")
    return Services(
        storage=storage,
        reader=reader,
        classifier=classifier,
        classifier_name="fake-mini",
        extractor=extractor,
        extractor_name="fake-big",
    )


async def _ingest(session: AsyncSession, services: Services) -> uuid.UUID:
    document = await ingest(
        session, services.storage, filename="doc-0001.pdf", content=PDF, max_bytes=10_000
    )
    await session.commit()
    return document.id


async def _count(session: AsyncSession, model: type) -> int:
    return (await session.execute(select(func.count()).select_from(model))).scalar_one()


async def _extraction(session: AsyncSession, variant: str) -> ExtractedInvoice:
    row = (
        await session.execute(select(Extraction).where(Extraction.variant == variant))
    ).scalar_one()
    return ExtractedInvoice.model_validate(row.data)


async def test_invoice_goes_through_all_steps(
    session_factory: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    services = _services()
    document_id = await _ingest(session, services)

    label = await process_document(session_factory, services, document_id, extract.VARIANTS)

    assert label == "invoice"
    document = await session.get(Document, document_id, populate_existing=True)
    assert document is not None
    assert (document.document_type, document.status) == (
        "invoice",
        DocumentStatus.PROCESSING.value,
    )
    assert await _count(session, Reading) == 2
    assert await _count(session, Classification) == 1
    assert await _count(session, Extraction) == 3
    for variant in extract.VARIANTS:
        assert (await _extraction(session, variant)).fields["total"].value == "1234.56"
    steps_logged = (
        (await session.execute(select(AuditRecord.step).order_by(AuditRecord.seq))).scalars().all()
    )
    assert steps_logged == [
        "uploaded",
        "read_text",
        "classified:classify_v1|fake-mini",
        "read_invoice_fields",
        "extracted:combined|extract_invoice_v1|fake-big",
        "extracted:llm_only|extract_invoice_v1|fake-big",
        "extracted:di_only",
    ]
    assert (await audit.verify_chain(session)).ok


async def test_usage_is_recorded_per_call(
    session_factory: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    services = _services()
    document_id = await _ingest(session, services)

    await process_document(session_factory, services, document_id, extract.VARIANTS)

    usage = (await session.execute(select(UsageRecord))).scalars().all()
    by_model = sorted((record.service, record.model) for record in usage)
    assert by_model == [
        ("chat", "fake-big"),
        ("chat", "fake-big"),
        ("chat", "fake-mini"),
        ("document_intelligence", "prebuilt-invoice"),
        ("document_intelligence", "prebuilt-read"),
    ]
    reading = next(record for record in usage if record.model == "prebuilt-read")
    assert reading.pages == 1
    chat = next(record for record in usage if record.model == "fake-mini")
    assert chat.input_tokens > 0
    assert chat.output_tokens > 0


async def test_running_twice_calls_nothing_twice(
    session_factory: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    """Rule 2: every step is safe to receive twice."""
    services = _services()
    document_id = await _ingest(session, services)

    first = await process_document(session_factory, services, document_id, extract.VARIANTS)
    second = await process_document(session_factory, services, document_id, extract.VARIANTS)

    assert first == second == "invoice"
    assert isinstance(services.reader, FakeDocumentReader)
    assert services.reader.calls == ["read_text", "read_invoice_fields"]
    assert isinstance(services.classifier, FakeChatModel)
    assert isinstance(services.extractor, FakeChatModel)
    assert len(services.classifier.calls) == 1
    assert len(services.extractor.calls) == 2
    assert await _count(session, Extraction) == 3
    assert await _count(session, UsageRecord) == 5
    assert await _count(session, AuditRecord) == 7


@pytest.mark.parametrize("label", ["contract", "other"])
async def test_other_documents_stop_after_classification(
    session_factory: async_sessionmaker[AsyncSession], session: AsyncSession, label: str
) -> None:
    services = _services(label=label)
    document_id = await _ingest(session, services)

    result = await process_document(session_factory, services, document_id, extract.VARIANTS)

    assert result == label
    assert isinstance(services.reader, FakeDocumentReader)
    assert services.reader.calls == ["read_text"]  # no paid invoice pass
    assert isinstance(services.extractor, FakeChatModel)
    assert services.extractor.calls == []
    assert await _count(session, Extraction) == 0


async def test_combined_flags_disagreement_and_logs_field_names_only(
    session_factory: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    services = _services(invoice_number="F2026-0007")
    document_id = await _ingest(session, services)

    await process_document(session_factory, services, document_id, [extract.VARIANT_COMBINED])

    invoice = await _extraction(session, extract.VARIANT_COMBINED)
    assert invoice.fields["invoice_number"].flags == [FLAG_DI_DISAGREES]
    record = (
        await session.execute(select(AuditRecord).where(AuditRecord.step.like("extracted:%")))
    ).scalar_one()
    assert record.payload == {"flagged_fields": ["invoice_number"], "line_items": 0}


async def test_no_document_content_reaches_the_audit_log(
    session_factory: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    """Rule 8, checked on everything the pipeline wrote."""
    services = _services()
    document_id = await _ingest(session, services)

    await process_document(session_factory, services, document_id, extract.VARIANTS)

    payloads = (await session.execute(select(AuditRecord.payload))).scalars().all()
    logged = " ".join(str(payload) for payload in payloads)
    for secret in ("F2026-0001", "1234.56", "1.234,56", "doc-0001.pdf", "FACTUUR"):
        assert secret not in logged


async def test_a_new_model_or_prompt_gives_a_new_run(session: AsyncSession) -> None:
    services = _services()

    assert steps.extract_run_key(services, "combined") == "combined|extract_invoice_v1|fake-big"
    assert steps.extract_run_key(services, "di_only") == "di_only"
    assert steps.classify_run_key(services) == "classify_v1|fake-mini"
    with pytest.raises(ValueError, match="unknown extraction variant"):
        await steps.extract_invoice(session, services, uuid.uuid4(), "best")
