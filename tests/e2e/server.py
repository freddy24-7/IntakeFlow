"""The application for the browser tests: real pages, real database, fake services.

Started by tests/e2e/conftest.py as `uvicorn tests.e2e.server:app`. The fakes
answer from the ground truth of a small synthetic set, so no Azure is needed.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date

from evaluation.oracle import oracle_services
from fastapi import FastAPI
from langgraph.checkpoint.memory import InMemorySaver
from synthetic.build import generate
from synthetic.write import render_document

from app.config import get_settings
from app.db.base import create_engine, create_session_factory
from app.main import create_app
from app.storage.local import MemoryStorage
from app.validation.purchase_orders import upsert_purchase_orders
from app.workflow.dispatch import InProcessDispatcher
from app.workflow.graph import build_graph

SEED = 21
DOCUMENTS = 40


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    dataset = generate(DOCUMENTS, SEED)
    documents = [
        (truth, render_document(truth, dataset.plans[truth.doc_id]))
        for truth in dataset.documents
        if not truth.scanned
    ]
    storage = MemoryStorage()
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    async with session_factory() as session:
        orders = [order.model_dump(mode="json") for order in dataset.purchase_orders]
        await upsert_purchase_orders(session, orders)
        await session.commit()

    graph = build_graph(
        session_factory,
        oracle_services(documents, storage),
        settings,
        checkpointer=InMemorySaver(),
        today=lambda: date(2026, 10, 12),
    )
    dispatcher = InProcessDispatcher(graph, session_factory, settings.max_attempts)
    application.state.session_factory = session_factory
    application.state.storage = storage
    application.state.dispatcher = dispatcher
    yield
    await dispatcher.wait()
    await engine.dispose()


app = create_app(lifespan)
