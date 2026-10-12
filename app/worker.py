"""The worker: takes document ids off the queue and runs the workflow.

    python -m app.worker

In Azure it runs as its own Container App that scales on the length of the
queue, down to zero when there is nothing to do.
"""

import asyncio
import contextlib
import logging
import signal
import uuid
from typing import Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.db.base import create_engine, create_session_factory
from app.db.models import Document, DocumentStatus
from app.observability.telemetry import configure_telemetry
from app.workflow.graph import build_graph, run_document
from app.workflow.queue import AzureQueue, JobQueue, QueueMessage
from app.workflow.services import build_azure_services, checkpoint_url

logger = logging.getLogger(__name__)
# Long enough for one document, including retries of throttled calls.
VISIBILITY_TIMEOUT_SECONDS = 600


async def handle(
    message: QueueMessage,
    queue: JobQueue,
    graph: Any,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    """Process one message. It is deleted when the document has a result or is
    parked as failed. Otherwise it stays on the queue and is tried again."""
    try:
        document_id = uuid.UUID(message.body)
    except ValueError:
        logger.error("dropping a queue message that is not a document id")
        await queue.delete(message)
        return

    result = await run_document(
        graph, session_factory, document_id, max_attempts=settings.max_attempts
    )
    if result is not None:
        await queue.delete(message)
        return
    async with session_factory() as session:
        document = await session.get(Document, document_id)
    if document is None or document.status == DocumentStatus.FAILED.value:
        # Unknown, or failed for the last time: the dead letter is the document's status.
        await queue.delete(message)
        logger.error("document %s parked as failed", document_id)
    else:
        logger.warning("document %s failed, it stays on the queue", document_id)


async def work(
    queue: JobQueue,
    graph: Any,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    stop: asyncio.Event,
    *,
    idle_seconds: float = 2.0,
) -> None:
    """Take messages until asked to stop. A document in progress is finished first."""
    while not stop.is_set():
        messages = await queue.receive(limit=1, visibility_timeout=VISIBILITY_TIMEOUT_SECONDS)
        if not messages:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=idle_seconds)
            continue
        for message in messages:
            await handle(message, queue, graph, session_factory, settings)


async def main() -> None:
    settings = get_settings()
    configure_telemetry(settings, service_name="intakeflow-worker")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for stop_signal in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(stop_signal, stop.set)

    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    queue = AzureQueue.connect(
        account_url=settings.azure_storage_queue_url, queue=settings.queue_name
    )
    async with AsyncPostgresSaver.from_conn_string(
        checkpoint_url(settings.database_url)
    ) as checkpointer:
        await checkpointer.setup()
        graph = build_graph(
            session_factory, build_azure_services(settings), settings, checkpointer=checkpointer
        )
        logger.info("worker started")
        await work(queue, graph, session_factory, settings, stop)
    await queue.close()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
