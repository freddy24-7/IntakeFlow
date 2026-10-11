"""Hands an uploaded document to the pipeline.

An in-process background task for now, behind a small interface. Stage 6
replaces it with Azure Queue Storage without the upload code changing.
"""

import asyncio
import logging
import uuid
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.workflow.runner import process_document
from app.workflow.steps import Services

logger = logging.getLogger(__name__)


class Dispatcher(Protocol):
    async def dispatch(self, document_id: uuid.UUID) -> None: ...


class NotConfiguredDispatcher:
    """Used when Azure is not configured: the document is stored and waits."""

    async def dispatch(self, document_id: uuid.UUID) -> None:
        logger.warning("document %s stored but not processed: Azure not configured", document_id)


class InProcessDispatcher:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        services: Services,
        variant: str,
    ) -> None:
        self._session_factory = session_factory
        self._services = services
        self._variant = variant
        self._tasks: set[asyncio.Task[None]] = set()

    async def dispatch(self, document_id: uuid.UUID) -> None:
        task = asyncio.create_task(self._run(document_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run(self, document_id: uuid.UUID) -> None:
        try:
            await process_document(
                self._session_factory, self._services, document_id, [self._variant]
            )
        except Exception as error:
            # Rule 8: log the id and the kind of error, not the message, which
            # can quote the document. Dead-letter handling arrives in stage 3.
            logger.error("document %s failed: %s", document_id, type(error).__name__)

    async def wait(self) -> None:
        """Wait for running documents. Used by tests and on shutdown."""
        await asyncio.gather(*self._tasks)
