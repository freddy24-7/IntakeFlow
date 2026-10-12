"""FastAPI application entry point."""

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.auth.demo import NotSignedIn
from app.config import get_settings
from app.db.base import create_engine, create_session_factory
from app.observability.telemetry import configure_telemetry
from app.validation.purchase_orders import seed_from_file
from app.web.health import router as health_router
from app.web.pages import router as pages_router
from app.web.upload import router as upload_router
from app.workflow.dispatch import InProcessDispatcher, NotConfiguredDispatcher
from app.workflow.graph import build_graph
from app.workflow.queue import AzureQueue, QueueDispatcher
from app.workflow.services import (
    azure_is_configured,
    build_azure_services,
    build_storage,
    checkpoint_url,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_telemetry(settings, service_name="intakeflow-web")
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    if settings.seed_purchase_orders_file is not None:
        async with session_factory() as session:
            count = await seed_from_file(session, settings.seed_purchase_orders_file)
        logger.info("loaded %d purchase orders", count)
    app.state.session_factory = session_factory
    app.state.storage = build_storage(settings)
    app.state.dispatcher = NotConfiguredDispatcher()
    app.state.services = None
    if not azure_is_configured(settings):
        yield
        await engine.dispose()
        return

    services = build_azure_services(settings)
    app.state.services = services
    if settings.dispatch_backend == "queue":
        # The worker runs the workflow. The web application only hands documents over.
        queue = AzureQueue.connect(
            account_url=settings.azure_storage_queue_url, queue=settings.queue_name
        )
        app.state.dispatcher = QueueDispatcher(queue)
        yield
        await queue.close()
        await engine.dispose()
        return

    async with AsyncPostgresSaver.from_conn_string(
        checkpoint_url(settings.database_url)
    ) as checkpointer:
        await checkpointer.setup()  # creates the checkpoint tables on first start
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
