"""Shared set-up for tests that push synthetic documents through the workflow with fakes."""

import uuid
from datetime import date
from typing import Any

from evaluation.oracle import oracle_services
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from synthetic.build import Dataset
from synthetic.truth import DocumentTruth
from synthetic.write import render_document

from app.config import Settings
from app.storage.local import MemoryStorage
from app.validation.purchase_orders import upsert_purchase_orders
from app.workflow.graph import build_graph, run_document
from app.workflow.ingest import ingest
from app.workflow.steps import Services

TODAY = date(2026, 10, 12)
Documents = list[tuple[DocumentTruth, bytes]]


def pick(dataset: Dataset, *, case: str | None = None, doc_type: str = "invoice") -> DocumentTruth:
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
