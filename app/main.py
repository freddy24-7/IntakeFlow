"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.db.base import create_engine, create_session_factory
from app.storage.local import LocalStorage
from app.web.health import router as health_router
from app.web.upload import router as upload_router
from app.workflow.dispatch import Dispatcher, InProcessDispatcher, NotConfiguredDispatcher
from app.workflow.services import azure_is_configured, build_azure_services


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    dispatcher: Dispatcher = NotConfiguredDispatcher()
    if azure_is_configured(settings):
        dispatcher = InProcessDispatcher(
            session_factory, build_azure_services(settings), settings.extraction_variant
        )
    app.state.session_factory = session_factory
    app.state.storage = LocalStorage(settings.storage_dir)
    app.state.dispatcher = dispatcher
    yield
    await engine.dispose()


app = FastAPI(title="IntakeFlow", lifespan=lifespan)
app.include_router(health_router)
app.include_router(upload_router)
