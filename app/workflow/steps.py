"""The pipeline steps of stage 2: read text, classify, read fields, extract.

Rule 2: each step reads its input from the database and writes its output to
the database, and a step that already ran (recognised by its audit record) is
skipped. The caller commits after each step, so a step's output, its usage
record and its audit record land together or not at all.

Audit payloads hold counts, labels and flags only, never document content (rule 8).
"""

import time
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import extract as extraction
from app.agents.classify import classify
from app.agents.prompts import CLASSIFY, EXTRACT_INVOICE, load_prompt
from app.agents.schema import INVOICE_LABELS, ExtractedInvoice
from app.audit import log as audit
from app.db.models import Classification, Document, DocumentStatus, Extraction, Reading, UsageRecord
from app.inference.interfaces import ChatModel, EmbeddingModel, ModelUsage
from app.rag.interfaces import SearchIndex
from app.reading.interfaces import (
    DocumentReader,
    ReadResult,
    read_result_from_dict,
    read_result_to_dict,
)
from app.storage.interfaces import Storage

STEP_READ_TEXT = "read_text"
STEP_READ_FIELDS = "read_invoice_fields"
KIND_TEXT, KIND_INVOICE_FIELDS = "text", "invoice_fields"
SERVICE_READING, SERVICE_CHAT = "document_intelligence", "chat"
READ_MODEL, INVOICE_MODEL = "prebuilt-read", "prebuilt-invoice"


@dataclass(frozen=True)
class Services:
    """Everything a step needs from outside the database."""

    storage: Storage
    reader: DocumentReader
    classifier: ChatModel
    classifier_name: str
    extractor: ChatModel
    extractor_name: str
    # Contract search (stage 5). Optional, so invoice-only set-ups need none of it.
    embedder: EmbeddingModel | None = None
    embedder_name: str = ""
    search: SearchIndex | None = None
    search_name: str = ""
    answerer: ChatModel | None = None
    answerer_name: str = ""


def classify_run_key(services: Services) -> str:
    return run_key(CLASSIFY, services.classifier_name)


def extract_run_key(services: Services, variant: str) -> str:
    """A new prompt version or model gives a new key, so the step runs again
    and both results stay available for comparison."""
    if variant == extraction.VARIANT_DI_ONLY:
        return run_key(variant, extraction.DI_MAPPING_VERSION)
    return run_key(variant, EXTRACT_INVOICE, services.extractor_name)


def run_key(*parts: str) -> str:
    key = "|".join(parts)
    if len(key) > 52:  # "classified:" plus the key must fit the 64-character step column
        raise ValueError(f"run key too long for the audit log: {key}")
    return key


async def _document(session: AsyncSession, document_id: uuid.UUID) -> Document:
    document = await session.get(Document, document_id)
    if document is None:
        raise LookupError(f"document {document_id} does not exist")
    return document


async def stored_reading(session: AsyncSession, document_id: uuid.UUID, kind: str) -> ReadResult:
    row = (
        await session.execute(
            select(Reading).where(Reading.document_id == document_id, Reading.kind == kind)
        )
    ).scalar_one()
    return read_result_from_dict(row.result)


def _chat_usage(document_id: uuid.UUID, step: str, usage: ModelUsage) -> UsageRecord:
    return UsageRecord(
        document_id=document_id,
        step=step,
        service=SERVICE_CHAT,
        model=usage.model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        latency_ms=usage.latency_ms,
    )


async def _read(
    session: AsyncSession, services: Services, document_id: uuid.UUID, *, step: str, kind: str
) -> None:
    if await audit.step_already_ran(session, document_id, step):
        return
    document = await _document(session, document_id)
    if document.storage_key is None:
        raise LookupError(f"document {document_id} has no stored file")
    content = await services.storage.load(document.storage_key)

    started = time.perf_counter()
    if kind == KIND_TEXT:
        result = await services.reader.read_text(content)
    else:
        result = await services.reader.read_invoice_fields(content)
    latency_ms = (time.perf_counter() - started) * 1000

    pages = len(result.pages)
    session.add(
        Reading(
            document_id=document_id,
            kind=kind,
            page_count=pages,
            result=read_result_to_dict(result),
        )
    )
    session.add(
        UsageRecord(
            document_id=document_id,
            step=step,
            service=SERVICE_READING,
            model=READ_MODEL if kind == KIND_TEXT else INVOICE_MODEL,
            pages=pages,
            latency_ms=latency_ms,
        )
    )
    if kind == KIND_TEXT:
        document.status = DocumentStatus.PROCESSING.value
    await audit.append(
        session,
        step=step,
        document_id=document_id,
        payload={"pages": pages, "fields": len(result.fields)},
    )


async def read_text(session: AsyncSession, services: Services, document_id: uuid.UUID) -> None:
    """Text for every document, before classification."""
    await _read(session, services, document_id, step=STEP_READ_TEXT, kind=KIND_TEXT)


async def read_invoice_fields(
    session: AsyncSession, services: Services, document_id: uuid.UUID
) -> None:
    """Prebuilt invoice fields. Only called for invoices and credit notes."""
    await _read(session, services, document_id, step=STEP_READ_FIELDS, kind=KIND_INVOICE_FIELDS)


async def classify_document(
    session: AsyncSession, services: Services, document_id: uuid.UUID
) -> str:
    """Classify and return the label. On a repeat call the stored label is returned."""
    run_key = classify_run_key(services)
    step = f"classified:{run_key}"
    if await audit.step_already_ran(session, document_id, step):
        stored = await session.execute(
            select(Classification.label).where(
                Classification.document_id == document_id, Classification.run_key == run_key
            )
        )
        return stored.scalar_one()

    reading = await stored_reading(session, document_id, KIND_TEXT)
    answer, usage = await classify(services.classifier, load_prompt(CLASSIFY), reading)
    session.add(
        Classification(
            document_id=document_id,
            run_key=run_key,
            label=answer.label,
            confidence=answer.confidence,
        )
    )
    session.add(_chat_usage(document_id, step, usage))
    (await _document(session, document_id)).document_type = answer.label
    await audit.append(
        session,
        step=step,
        document_id=document_id,
        payload={"label": answer.label, "confidence": f"{answer.confidence:.2f}"},
    )
    return answer.label


async def extract_invoice(
    session: AsyncSession, services: Services, document_id: uuid.UUID, variant: str
) -> None:
    if variant not in extraction.VARIANTS:
        raise ValueError(f"unknown extraction variant: {variant}")
    run_key = extract_run_key(services, variant)
    step = f"extracted:{run_key}"
    if await audit.step_already_ran(session, document_id, step):
        return

    invoice: ExtractedInvoice
    if variant == extraction.VARIANT_DI_ONLY:
        fields = (await stored_reading(session, document_id, KIND_INVOICE_FIELDS)).fields
        invoice = extraction.di_fields_to_invoice(fields)
    else:
        reading = await stored_reading(session, document_id, KIND_TEXT)
        di_fields = None
        if variant == extraction.VARIANT_COMBINED:
            di_fields = (await stored_reading(session, document_id, KIND_INVOICE_FIELDS)).fields
        invoice, usage = await extraction.extract_with_model(
            services.extractor, load_prompt(EXTRACT_INVOICE), reading, di_fields
        )
        session.add(_chat_usage(document_id, step, usage))

    session.add(
        Extraction(
            document_id=document_id,
            run_key=run_key,
            variant=variant,
            data=invoice.model_dump(mode="json"),
        )
    )
    flagged = sorted(name for name, field in invoice.fields.items() if field.flags)
    await audit.append(
        session,
        step=step,
        document_id=document_id,
        payload={"flagged_fields": list(flagged), "line_items": len(invoice.line_items)},
    )


def needs_extraction(label: str) -> bool:
    return label in INVOICE_LABELS
