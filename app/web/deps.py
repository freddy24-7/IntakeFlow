"""FastAPI dependencies. Tests replace them through `app.dependency_overrides`."""

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.storage.interfaces import Storage
from app.workflow.dispatch import Dispatcher


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.session_factory() as session:
        yield session


def get_storage(request: Request) -> Storage:
    storage: Storage = request.app.state.storage
    return storage


def get_dispatcher(request: Request) -> Dispatcher:
    dispatcher: Dispatcher = request.app.state.dispatcher
    return dispatcher
