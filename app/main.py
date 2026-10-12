"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import make_url

from app.config import get_settings
from app.db.base import create_engine, create_session_factory
from app.storage.local import LocalStorage
from app.web.health import router as health_router
from app.web.upload import router as upload_router
from app.workflow.dispatch import InProcessDispatcher, NotConfiguredDispatcher
from app.workflow.graph import build_graph
from app.workflow.services import azure_is_configured, build_azure_services


def checkpoint_url(database_url: str) -> str:
    """LangGraph's Postgres checkpointer uses psycopg, the rest of the app asyncpg."""
    return make_url(database_url).set(drivername="postgresql").render_as_string(hide_password=False)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    app.state.session_factory = session_factory
    app.state.storage = LocalStorage(settings.storage_dir)
    app.state.dispatcher = NotConfiguredDispatcher()
    if not azure_is_configured(settings):
        yield
        await engine.dispose()
        return

    async with AsyncPostgresSaver.from_conn_string(
        checkpoint_url(settings.database_url)
    ) as checkpointer:
        await checkpointer.setup()  # creates the checkpoint tables on first start
        graph = build_graph(
            session_factory, build_azure_services(settings), settings, checkpointer=checkpointer
        )
        dispatcher = InProcessDispatcher(graph, session_factory, settings.max_attempts)
        app.state.dispatcher = dispatcher
        yield
        await dispatcher.wait()
    await engine.dispose()


app = FastAPI(title="IntakeFlow", lifespan=lifespan)
app.include_router(health_router)
app.include_router(upload_router)
