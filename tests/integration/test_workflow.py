"""The LangGraph workflow with fakes: routing, the ERP, retries, dead letters and resuming."""

import uuid
from collections.abc import AsyncIterator
from datetime import date
from typing import Any

import pytest
from evaluation.oracle import oracle_services
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import URL, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from synthetic.build import Dataset, generate
from synthetic.truth import DocumentTruth
from synthetic.write import render_document

from app.audit import log as audit
from app.config import Settings
from app.db.models import AuditRecord, Document, DocumentStatus, RoutingDecision, Validation
from app.reading.fakes import FakeDocumentReader
from app.reading.interfaces import ReadResult
from app.storage.local import MemoryStorage
from app.validation.purchase_orders import upsert_purchase_orders
from app.workflow.graph import build_graph, run_document
from app.workflow.ingest import ingest
from app.workflow.steps import Services

TODAY = date(2026, 10, 12)
Documents = list[tuple[DocumentTruth, bytes]]


@pytest.fixture(scope="module")
def dataset() -> Dataset:
    return generate(60, seed=11)


def _pick(dataset: Dataset, *, case: str | None = None, doc_type: str = "invoice") -> DocumentTruth:
    """A digital document of the type, with exactly this hard case (or none)."""
    wanted = [case] if case else []
    return next(
        doc
        for doc in dataset.documents
        if doc.doc_type == doc_type and doc.hard_cases == wanted and not doc.scanned
    )


class Pipeline:
    """Everything a test needs to push documents through the graph."""

    def __init__(
        self,
        dataset: Dataset,
        session_factory: async_sessionmaker[AsyncSession],
        truths: list[DocumentTruth],
        *,
        settings: Settings | None = None,
        checkpointer: Any = None,
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings or Settings(_env_file=None, database_url="unused")
        self.documents: Documents = [
            (truth, render_document(truth, dataset.plans[truth.doc_id])) for truth in truths
        ]
        self.services: Services = oracle_services(self.documents, MemoryStorage())
        self.orders = [order.model_dump(mode="json") for order in dataset.purchase_orders]
        self.checkpointer = checkpointer or InMemorySaver()
        self.graph = self.build()

    def build(self) -> Any:
        return build_graph(
            self.session_factory,
            self.services,
            self.settings,
            checkpointer=self.checkpointer,
            today=lambda: TODAY,
            retry_initial_interval=0.01,
        )

    async def ingest(self, truth: DocumentTruth) -> uuid.UUID:
        content = next(content for candidate, content in self.documents if candidate is truth)
        async with self.session_factory() as session:
            await upsert_purchase_orders(session, self.orders)
            document = await ingest(
                session,
                self.services.storage,
                filename=truth.filename,
                content=content,
                max_bytes=10_000_000,
            )
            await session.commit()
            return document.id

    async def run(self, document_id: uuid.UUID) -> Any:
        return await run_document(
            self.graph, self.session_factory, document_id, max_attempts=self.settings.max_attempts
        )

    async def process(self, truth: DocumentTruth) -> uuid.UUID:
        document_id = await self.ingest(truth)
        await self.run(document_id)
        return document_id


async def _status(session: AsyncSession, document_id: uuid.UUID) -> str:
    document = await session.get(Document, document_id, populate_existing=True)
    assert document is not None
    return document.status


async def _erp_count(session: AsyncSession) -> int:
    count: int = (await session.execute(text("SELECT count(*) FROM erp_entries"))).scalar_one()
    return count


async def _decision(session: AsyncSession, document_id: uuid.UUID) -> RoutingDecision:
    return (
        await session.execute(
            select(RoutingDecision).where(RoutingDecision.document_id == document_id)
        )
    ).scalar_one()


async def test_clean_invoice_is_auto_approved_and_booked(
    session_factory: async_sessionmaker[AsyncSession], session: AsyncSession, dataset: Dataset
) -> None:
    truth = _pick(dataset)
    pipeline = Pipeline(dataset, session_factory, [truth])

    document_id = await pipeline.ingest(truth)
    state = await pipeline.run(document_id)

    assert state == {
        "document_id": str(document_id),
        "label": "invoice",
        "decision": "auto_approve",
    }
    assert await _status(session, document_id) == DocumentStatus.AUTO_APPROVED.value
    assert await _erp_count(session) == 1
    decision = await _decision(session, document_id)
    # Validation alone decides at the configured threshold of 0.
    assert (decision.decision, decision.reasons, decision.threshold) == ("auto_approve", [], 0.0)
    assert decision.score >= 0.9
    steps_logged = (
        (await session.execute(select(AuditRecord.step).order_by(AuditRecord.seq))).scalars().all()
    )
    assert [step.split(":")[0] for step in steps_logged] == [
        "uploaded",
        "read_text",
        "classified",
        "read_invoice_fields",
        "extracted",
        "validated",
        "routed",
        "erp_posted",
        "decision_applied",
    ]
    assert (await audit.verify_chain(session)).ok


@pytest.mark.parametrize(
    ("case", "failure"),
    [
        ("wrong_iban", "iban_checksum"),
        ("totals_mismatch", "totals_mismatch"),
        ("missing_po", "po_missing"),
        ("unknown_po", "po_not_found"),
        ("po_supplier_mismatch", "po_supplier_mismatch"),
        ("po_amount_mismatch", "po_amount_out_of_tolerance"),
        ("due_before_invoice", "due_date_before_invoice_date"),
        ("invalid_vat_number", "vat_number_format"),
    ],
)
async def test_a_labelled_problem_goes_to_review_despite_a_near_perfect_score(
    session_factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    dataset: Dataset,
    case: str,
    failure: str,
) -> None:
    """Rule 3 end to end: extraction is perfect and confident, the check still wins."""
    candidates = [doc for doc in dataset.documents if doc.hard_cases == [case] and not doc.scanned]
    if not candidates:
        pytest.skip(f"seed has no digital document with only {case}")
    truth = candidates[0]
    pipeline = Pipeline(dataset, session_factory, [truth])

    document_id = await pipeline.process(truth)

    decision = await _decision(session, document_id)
    assert decision.score >= 0.9
    assert decision.decision == "review"
    assert failure in decision.reasons
    assert await _status(session, document_id) == DocumentStatus.IN_REVIEW.value
    assert await _erp_count(session) == 0


async def test_low_score_goes_to_review_although_every_check_passes(
    session_factory: async_sessionmaker[AsyncSession], session: AsyncSession, dataset: Dataset
) -> None:
    truth = _pick(dataset)
    strict = Settings(_env_file=None, database_url="unused", auto_approve_threshold=0.995)
    pipeline = Pipeline(dataset, session_factory, [truth], settings=strict)

    document_id = await pipeline.process(truth)

    decision = await _decision(session, document_id)
    assert (decision.decision, decision.reasons) == ("review", ["score_below_threshold"])
    failures = (await session.execute(select(Validation.failures))).scalar_one()
    assert failures == []
    assert await _erp_count(session) == 0


async def test_duplicate_invoice_is_caught_on_the_second_copy(
    session_factory: async_sessionmaker[AsyncSession], session: AsyncSession, dataset: Dataset
) -> None:
    duplicate = next(
        doc
        for doc in dataset.documents
        if doc.hard_cases == ["duplicate"]
        and not next(d for d in dataset.documents if d.doc_id == doc.duplicate_of).scanned
    )
    original = next(doc for doc in dataset.documents if doc.doc_id == duplicate.duplicate_of)
    pipeline = Pipeline(dataset, session_factory, [original, duplicate])

    first = await pipeline.process(original)
    second = await pipeline.process(duplicate)

    assert await _status(session, first) == DocumentStatus.AUTO_APPROVED.value
    assert await _status(session, second) == DocumentStatus.IN_REVIEW.value
    assert "duplicate_invoice" in (await _decision(session, second)).reasons
    assert await _erp_count(session) == 1


async def test_other_mail_goes_to_review_and_contracts_wait(
    session_factory: async_sessionmaker[AsyncSession], session: AsyncSession, dataset: Dataset
) -> None:
    other = _pick(dataset, doc_type="other")
    contract = _pick(dataset, doc_type="contract")
    pipeline = Pipeline(dataset, session_factory, [other, contract])

    other_id = await pipeline.process(other)
    contract_id = await pipeline.process(contract)

    assert await _status(session, other_id) == DocumentStatus.IN_REVIEW.value
    assert await _status(session, contract_id) == DocumentStatus.PROCESSING.value
    assert isinstance(pipeline.services.reader, FakeDocumentReader)
    assert pipeline.services.reader.calls == ["read_text", "read_text"]
    assert await _erp_count(session) == 0


async def test_running_a_finished_document_again_changes_nothing(
    session_factory: async_sessionmaker[AsyncSession], session: AsyncSession, dataset: Dataset
) -> None:
    truth = _pick(dataset)
    pipeline = Pipeline(dataset, session_factory, [truth])
    document_id = await pipeline.process(truth)
    records_before = (await audit.verify_chain(session)).records_checked

    await pipeline.run(document_id)

    assert (await audit.verify_chain(session)).records_checked == records_before
    assert await _erp_count(session) == 1


class FlakyReader:
    """Fails a number of times with a connection error, then behaves."""

    def __init__(self, inner: Any, failures: int) -> None:
        self.inner = inner
        self.failures = failures
        self.attempts = 0

    async def read_text(self, content: bytes) -> ReadResult:
        self.attempts += 1
        if self.attempts <= self.failures:
            raise ConnectionError("throttled")
        result: ReadResult = await self.inner.read_text(content)
        return result

    async def read_invoice_fields(self, content: bytes) -> ReadResult:
        result: ReadResult = await self.inner.read_invoice_fields(content)
        return result


def _with_reader(pipeline: Pipeline, reader: Any) -> None:
    services = pipeline.services
    pipeline.services = Services(
        storage=services.storage,
        reader=reader,
        classifier=services.classifier,
        classifier_name=services.classifier_name,
        extractor=services.extractor,
        extractor_name=services.extractor_name,
    )
    pipeline.graph = pipeline.build()


async def test_a_throttled_call_is_retried_within_the_run(
    session_factory: async_sessionmaker[AsyncSession], session: AsyncSession, dataset: Dataset
) -> None:
    truth = _pick(dataset)
    pipeline = Pipeline(dataset, session_factory, [truth])
    flaky = FlakyReader(pipeline.services.reader, failures=2)
    _with_reader(pipeline, flaky)

    document_id = await pipeline.process(truth)

    assert flaky.attempts == 3
    assert await _status(session, document_id) == DocumentStatus.AUTO_APPROVED.value
    document = await session.get(Document, document_id)
    assert document is not None
    assert document.attempts == 0


async def test_a_document_that_keeps_failing_is_parked_as_failed(
    session_factory: async_sessionmaker[AsyncSession], session: AsyncSession, dataset: Dataset
) -> None:
    truth = _pick(dataset)
    pipeline = Pipeline(dataset, session_factory, [truth])
    _with_reader(pipeline, FlakyReader(pipeline.services.reader, failures=1000))
    document_id = await pipeline.ingest(truth)

    statuses = []
    for _ in range(3):
        assert await pipeline.run(document_id) is None
        statuses.append(await _status(session, document_id))

    assert statuses == ["received", "received", DocumentStatus.FAILED.value]
    document = await session.get(Document, document_id, populate_existing=True)
    assert document is not None
    assert (document.attempts, document.last_error) == (3, "ConnectionError")
    failures = (
        await session.execute(
            select(AuditRecord.step, AuditRecord.payload)
            .where(AuditRecord.step.in_(["attempt_failed", "dead_lettered"]))
            .order_by(AuditRecord.seq)
        )
    ).all()
    assert [step for step, _ in failures] == ["attempt_failed", "attempt_failed", "dead_lettered"]
    # Rule 8: the kind of error, not its message.
    assert failures[-1][1] == {"error": "ConnectionError", "attempt": 3}


@pytest.fixture
async def postgres_checkpointer(test_database_url: URL) -> AsyncIterator[AsyncPostgresSaver]:
    connection = test_database_url.set(drivername="postgresql").render_as_string(
        hide_password=False
    )
    async with AsyncPostgresSaver.from_conn_string(connection) as saver:
        await saver.setup()
        yield saver


async def test_a_failed_run_resumes_from_the_saved_state_in_postgres(
    session_factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    dataset: Dataset,
    postgres_checkpointer: AsyncPostgresSaver,
) -> None:
    truth = _pick(dataset)
    pipeline = Pipeline(dataset, session_factory, [truth], checkpointer=postgres_checkpointer)
    good_reader = pipeline.services.reader
    assert isinstance(good_reader, FakeDocumentReader)

    class FailsOnFields(FlakyReader):
        async def read_invoice_fields(self, content: bytes) -> ReadResult:
            raise ConnectionError("down")

    _with_reader(pipeline, FailsOnFields(good_reader, failures=0))
    document_id = await pipeline.ingest(truth)
    assert await pipeline.run(document_id) is None

    config = {"configurable": {"thread_id": str(document_id)}}
    stopped = await pipeline.graph.aget_state(config)
    assert stopped.next == ("read_fields",)
    assert stopped.values["label"] == "invoice"

    # The service is back. A new graph object, as after a restart of the app.
    _with_reader(pipeline, good_reader)
    state = await pipeline.run(document_id)

    assert state is not None
    assert state["decision"] == "auto_approve"
    assert await _status(session, document_id) == DocumentStatus.AUTO_APPROVED.value
    # Resumed after classification: the text was read once, not twice.
    assert good_reader.calls == ["read_text", "read_invoice_fields"]
