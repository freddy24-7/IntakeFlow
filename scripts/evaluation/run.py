"""Runs the labelled set through the pipeline and gathers what the report needs."""

import asyncio
import hashlib
import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from synthetic.truth import DocumentTruth

from app.agents.schema import ExtractedInvoice
from app.db.models import Classification, Document, Extraction, UsageRecord
from app.observability.prices import call_cost
from app.workflow import steps
from app.workflow.ingest import ingest
from app.workflow.runner import process_document
from app.workflow.steps import Services

MAX_UPLOAD_BYTES = 50 * 1024 * 1024


def load_dataset(directory: Path, limit: int | None) -> list[tuple[DocumentTruth, bytes]]:
    """Ground truth and PDF bytes, in document order."""
    documents = []
    for truth_path in sorted(directory.glob("doc-*.json"))[:limit]:
        truth = DocumentTruth.model_validate_json(truth_path.read_text(encoding="utf-8"))
        pdf_path = directory / truth.filename
        if not pdf_path.exists():
            raise FileNotFoundError(
                f"{pdf_path} is missing. Run scripts/generate_synthetic.py first."
            )
        documents.append((truth, pdf_path.read_bytes()))
    return documents


@dataclass
class DocumentResult:
    truth: DocumentTruth
    label: str | None = None
    classification_confidence: float | None = None
    extractions: dict[str, ExtractedInvoice] = field(default_factory=dict)
    error: str | None = None  # the kind of error, never its message (rule 8)


@dataclass
class StepUsage:
    latencies_ms: list[float] = field(default_factory=list)
    cost: Decimal = Decimal(0)
    calls: int = 0
    unpriced: bool = False


@dataclass
class RunResults:
    documents: list[DocumentResult]
    usage: dict[str, StepUsage]  # by step name


async def _ensure_ingested(
    session_factory: async_sessionmaker[AsyncSession],
    services: Services,
    documents: Sequence[tuple[DocumentTruth, bytes]],
    namespace: str,
) -> dict[str, uuid.UUID]:
    """Register each file once per namespace. A later run in the same namespace
    finds the same document again, so readings that were already paid for are
    reused. The namespace keeps runs with fakes apart from runs against Azure:
    without it a real run would reuse a fake reading."""
    ids = {}
    async with session_factory() as session:
        for truth, content in documents:
            digest = hashlib.sha256(content).hexdigest()
            filename = f"{namespace}/{truth.filename}"
            existing = await session.execute(
                select(Document.id).where(
                    Document.filename == filename, Document.content_sha256 == digest
                )
            )
            document_id = existing.scalars().first()
            if document_id is None:
                document = await ingest(
                    session,
                    services.storage,
                    filename=filename,
                    content=content,
                    max_bytes=MAX_UPLOAD_BYTES,
                )
                document_id = document.id
            ids[truth.doc_id] = document_id
        await session.commit()
    return ids


async def run_evaluation(
    session_factory: async_sessionmaker[AsyncSession],
    services: Services,
    documents: Sequence[tuple[DocumentTruth, bytes]],
    variants: Sequence[str],
    *,
    namespace: str,
    concurrency: int = 4,
) -> RunResults:
    ids = await _ensure_ingested(session_factory, services, documents, namespace)
    results = {truth.doc_id: DocumentResult(truth) for truth, _ in documents}
    limiter = asyncio.Semaphore(concurrency)

    async def run_one(doc_id: str) -> None:
        async with limiter:
            try:
                await process_document(session_factory, services, ids[doc_id], variants)
            except Exception as error:
                results[doc_id].error = type(error).__name__

    await asyncio.gather(*(run_one(doc_id) for doc_id in ids))

    classify_key = steps.classify_run_key(services)
    extract_keys = {steps.extract_run_key(services, variant): variant for variant in variants}
    step_names = {
        steps.STEP_READ_TEXT,
        steps.STEP_READ_FIELDS,
        f"classified:{classify_key}",
        *(f"extracted:{key}" for key in extract_keys),
    }
    usage: dict[str, StepUsage] = defaultdict(StepUsage)
    by_uuid = {document_id: doc_id for doc_id, document_id in ids.items()}

    async with session_factory() as session:
        labels = await session.execute(
            select(
                Classification.document_id, Classification.label, Classification.confidence
            ).where(
                Classification.run_key == classify_key,
                Classification.document_id.in_(by_uuid),
            )
        )
        for document_id, label, confidence in labels:
            results[by_uuid[document_id]].label = label
            results[by_uuid[document_id]].classification_confidence = confidence

        extractions = await session.execute(
            select(Extraction).where(
                Extraction.run_key.in_(extract_keys), Extraction.document_id.in_(by_uuid)
            )
        )
        for row in extractions.scalars():
            invoice = ExtractedInvoice.model_validate(row.data)
            results[by_uuid[row.document_id]].extractions[extract_keys[row.run_key]] = invoice

        records = await session.execute(
            select(UsageRecord).where(
                UsageRecord.step.in_(step_names), UsageRecord.document_id.in_(by_uuid)
            )
        )
        for record in records.scalars():
            entry = usage[record.step]
            entry.calls += 1
            entry.latencies_ms.append(record.latency_ms)
            cost = call_cost(
                model=record.model,
                pages=record.pages,
                input_tokens=record.input_tokens,
                output_tokens=record.output_tokens,
            )
            if cost is None:
                entry.unpriced = True
            else:
                entry.cost += cost

    return RunResults(documents=[results[truth.doc_id] for truth, _ in documents], usage=usage)
