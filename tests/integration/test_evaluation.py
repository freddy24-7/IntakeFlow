"""The evaluation harness, end to end with fakes that answer from the ground truth."""

from datetime import date
from pathlib import Path

import pytest
from evaluation.oracle import oracle_services
from evaluation.report import build_report
from evaluation.run import load_dataset, run_evaluation
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from synthetic.build import generate
from synthetic.truth import DocumentTruth
from synthetic.write import write_dataset

from app.agents.extract import VARIANTS
from app.agents.schema import ClassificationAnswer, LlmInvoice
from app.db.models import Document, UsageRecord
from app.inference.fakes import FakeChatModel
from app.storage.local import MemoryStorage

Dataset = list[tuple[DocumentTruth, bytes]]


@pytest.fixture(scope="module")
def dataset(tmp_path_factory: pytest.TempPathFactory) -> Dataset:
    directory = tmp_path_factory.mktemp("synthetic")
    write_dataset(generate(30, seed=7), directory)
    return load_dataset(directory / "documents", limit=None)


def _report(results: object, services: object) -> str:
    return build_report(
        results,  # type: ignore[arg-type]
        services,  # type: ignore[arg-type]
        VARIANTS,
        services_kind="oracle",
        seed=7,
        today=date(2026, 10, 11),
    )


async def test_perfect_answers_give_a_perfect_report(
    session_factory: async_sessionmaker[AsyncSession], dataset: Dataset
) -> None:
    services = oracle_services(dataset, MemoryStorage())

    results = await run_evaluation(
        session_factory, services, dataset, VARIANTS, namespace="test", concurrency=1
    )

    assert all(result.error is None for result in results.documents)
    assert all(result.label == result.truth.doc_type for result in results.documents)
    money = [result for result in results.documents if result.truth.invoice is not None]
    assert all(set(result.extractions) == set(VARIANTS) for result in money)
    report = _report(results, services)
    assert "**Not a measurement.**" in report
    assert "Accuracy: 100.0% (30/30)" in report
    assert f"| Combined | 100.0% ({len(money)}/{len(money)}) |" in report
    assert "combined\\|extract_invoice_v2\\|oracle" in report  # pipes escaped in tables
    assert "scanned" in report


async def test_a_second_run_reuses_documents_and_pays_for_nothing(
    session_factory: async_sessionmaker[AsyncSession], session: AsyncSession, dataset: Dataset
) -> None:
    services = oracle_services(dataset, MemoryStorage())

    async def run() -> tuple[int, int]:
        await run_evaluation(
            session_factory, services, dataset, VARIANTS, namespace="test", concurrency=1
        )
        documents = await session.execute(select(func.count()).select_from(Document))
        usage = await session.execute(select(func.count()).select_from(UsageRecord))
        return documents.scalar_one(), usage.scalar_one()

    first = await run()
    second = await run()

    assert first == second
    assert first[0] == 30


async def test_another_namespace_does_not_reuse_readings(
    session_factory: async_sessionmaker[AsyncSession], session: AsyncSession, dataset: Dataset
) -> None:
    """A run against Azure must never pick up a reading made by a fake."""
    services = oracle_services(dataset, MemoryStorage())
    for namespace in ("eval-oracle", "eval-azure"):
        await run_evaluation(
            session_factory, services, dataset[:5], VARIANTS, namespace=namespace, concurrency=1
        )

    filenames = (await session.execute(select(Document.filename))).scalars().all()
    assert len(filenames) == 10
    assert sum(name.startswith("eval-azure/") for name in filenames) == 5


async def test_wrong_answers_show_up_in_the_report(
    session_factory: async_sessionmaker[AsyncSession], dataset: Dataset
) -> None:
    """The harness built wrongly on purpose: a model that misreads every total
    and calls every credit note an invoice."""
    services = oracle_services(dataset, MemoryStorage())
    assert isinstance(services.extractor, FakeChatModel)
    assert isinstance(services.classifier, FakeChatModel)
    good_extract = services.extractor.answers[LlmInvoice]
    good_classify = services.classifier.answers[ClassificationAnswer]
    assert callable(good_extract)
    assert callable(good_classify)

    def bad_extract(user: str) -> BaseModel:
        invoice = good_extract(user)
        assert isinstance(invoice, LlmInvoice)
        invoice.total.value = "0.01"
        return invoice

    def bad_classify(user: str) -> BaseModel:
        answer = good_classify(user)
        assert isinstance(answer, ClassificationAnswer)
        if answer.label == "credit_note":
            answer.label = "invoice"
        return answer

    services.extractor.answers[LlmInvoice] = bad_extract
    services.classifier.answers[ClassificationAnswer] = bad_classify

    results = await run_evaluation(
        session_factory, services, dataset, VARIANTS, namespace="test", concurrency=1
    )

    money = sum(result.truth.invoice is not None for result in results.documents)
    credit_notes = sum(result.truth.doc_type == "credit_note" for result in results.documents)
    report = _report(results, services)
    assert f"Accuracy: {100 * (30 - credit_notes) / 30:.1f}% ({30 - credit_notes}/30)" in report
    assert f"| credit_note | invoice | {credit_notes} |" in report
    # The model variants get every total wrong. Document Intelligence only does not use the model.
    assert f"| total | 0.0% (0/{money}) | 0.0% (0/{money}) | 100.0% ({money}/{money}) |" in report
    assert f"| Combined | 0.0% (0/{money}) |" in report
    # Combined flags the totals, because Document Intelligence disagrees.
    assert f"| Wrong fields that were flagged | 100.0% ({money}/{money}) |" in report


def test_missing_pdfs_give_a_clear_error(tmp_path: Path) -> None:
    (tmp_path / "doc-0001.json").write_text(
        '{"doc_id":"doc-0001","filename":"doc-0001.pdf","doc_type":"other","language":"nl",'
        '"layout":"plain"}'
    )
    with pytest.raises(FileNotFoundError, match="generate_synthetic"):
        load_dataset(tmp_path, limit=None)
