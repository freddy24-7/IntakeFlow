"""Hands an uploaded document to the pipeline.

An in-process background task for now, behind a small interface. Stage 6
replaces it with Azure Queue Storage without the upload code changing.
"""

import asyncio
import logging
import uuid
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.workflow.graph import run_document

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
        graph: Any,
        session_factory: async_sessionmaker[AsyncSession],
        max_attempts: int,
    ) -> None:
        self._graph = graph
        self._session_factory = session_factory
        self._max_attempts = max_attempts
        self._tasks: set[asyncio.Task[None]] = set()

    async def dispatch(self, document_id: uuid.UUID) -> None:
        task = asyncio.create_task(self._run(document_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run(self, document_id: uuid.UUID) -> None:
        # run_document records failures on the document, so nothing is lost here.
        result = await run_document(
            self._graph, self._session_factory, document_id, max_attempts=self._max_attempts
        )
        if result is None:
            logger.error("document %s failed, see its audit records", document_id)

    async def wait(self) -> None:
        """Wait for running documents. Used by tests and on shutdown."""
        await asyncio.gather(*self._tasks)
