"""FastAPI application entry point."""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import make_url

from app.auth.demo import NotSignedIn
from app.config import get_settings
from app.db.base import create_engine, create_session_factory
from app.storage.local import LocalStorage
from app.web.health import router as health_router
from app.web.pages import router as pages_router
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
    app.state.services = None
    if not azure_is_configured(settings):
        yield
        await engine.dispose()
        return

    async with AsyncPostgresSaver.from_conn_string(
        checkpoint_url(settings.database_url)
    ) as checkpointer:
        await checkpointer.setup()  # creates the checkpoint tables on first start
        services = build_azure_services(settings)
        app.state.services = services
        graph = build_graph(session_factory, services, settings, checkpointer=checkpointer)
        dispatcher = InProcessDispatcher(graph, session_factory, settings.max_attempts)
        app.state.dispatcher = dispatcher
        yield
        await dispatcher.wait()
    await engine.dispose()


def create_app(app_lifespan: Callable[[FastAPI], AbstractAsyncContextManager[None]]) -> FastAPI:
    """Build the application. Tests pass their own lifespan to run it with fakes."""
    application = FastAPI(title="IntakeFlow", lifespan=app_lifespan)
    application.include_router(health_router)
    application.include_router(upload_router)
    application.include_router(pages_router)
    application.mount(
        "/static", StaticFiles(directory=Path(__file__).parent / "web" / "static"), name="static"
    )

    @application.exception_handler(NotSignedIn)
    async def to_role_picker(request: Request, error: NotSignedIn) -> RedirectResponse:
        return RedirectResponse("/", status_code=303)

    return application


app = create_app(lifespan)
