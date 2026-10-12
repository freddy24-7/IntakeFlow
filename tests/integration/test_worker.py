"""Stage 6: the queue and the worker, with an in-memory queue and fake services."""

import asyncio
import dataclasses
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from synthetic.build import Dataset

from app.db.models import Document, DocumentStatus
from app.reading.interfaces import ReadResult
from app.worker import handle, work
from app.workflow.queue import MemoryQueue, QueueDispatcher
from tests.integration.pipeline import Pipeline, pick


class Down:
    """A reader whose service is unavailable."""

    async def read_text(self, content: bytes) -> ReadResult:
        raise ConnectionError("down")

    async def read_invoice_fields(self, content: bytes) -> ReadResult:
        raise ConnectionError("down")


async def _status(session_factory: async_sessionmaker[AsyncSession], document_id: Any) -> str:
    async with session_factory() as session:
        document = await session.get(Document, document_id)
        assert document is not None
        return document.status


async def _handle_next(queue: MemoryQueue, pipeline: Pipeline) -> None:
    [message] = await queue.receive(limit=1, visibility_timeout=600)
    await handle(message, queue, pipeline.graph, pipeline.session_factory, pipeline.settings)


async def test_upload_is_queued_and_the_worker_processes_it(
    session_factory: async_sessionmaker[AsyncSession], dataset: Dataset
) -> None:
    truth = pick(dataset)
    pipeline = Pipeline(dataset, session_factory, [truth])
    queue = MemoryQueue()
    document_id = await pipeline.ingest(truth)

    await QueueDispatcher(queue).dispatch(document_id)
    assert [message.body for message in queue.waiting] == [str(document_id)]
    await _handle_next(queue, pipeline)

    assert await _status(session_factory, document_id) == DocumentStatus.AUTO_APPROVED.value
    assert queue.waiting == []
    assert queue.hidden == {}  # deleted, so it will not come back


async def test_a_failed_document_stays_on_the_queue_until_it_is_parked(
    session_factory: async_sessionmaker[AsyncSession], dataset: Dataset
) -> None:
    """A worker that fails does not lose the document: the message comes back
    after the visibility timeout. After the last attempt it is deleted, and the
    document's failed status is the dead letter."""
    truth = pick(dataset)
    pipeline = Pipeline(dataset, session_factory, [truth])
    pipeline.services = dataclasses.replace(pipeline.services, reader=Down())
    pipeline.graph = pipeline.build()
    queue = MemoryQueue()
    document_id = await pipeline.ingest(truth)
    await queue.send(str(document_id))

    for attempt in (1, 2):
        await _handle_next(queue, pipeline)
        assert len(queue.hidden) == 1, f"attempt {attempt}: the message must not be deleted"
        assert await _status(session_factory, document_id) == DocumentStatus.RECEIVED.value
        queue.release()  # the visibility timeout runs out

    await _handle_next(queue, pipeline)
    assert await _status(session_factory, document_id) == DocumentStatus.FAILED.value
    assert queue.hidden == {}
    assert queue.waiting == []


async def test_the_document_is_processed_once_the_service_is_back(
    session_factory: async_sessionmaker[AsyncSession], dataset: Dataset
) -> None:
    truth = pick(dataset)
    pipeline = Pipeline(dataset, session_factory, [truth])
    working = pipeline.services
    pipeline.services = dataclasses.replace(working, reader=Down())
    pipeline.graph = pipeline.build()
    queue = MemoryQueue()
    document_id = await pipeline.ingest(truth)
    await queue.send(str(document_id))
    await _handle_next(queue, pipeline)

    pipeline.services = working
    pipeline.graph = pipeline.build()
    queue.release()
    await _handle_next(queue, pipeline)

    assert await _status(session_factory, document_id) == DocumentStatus.AUTO_APPROVED.value
    assert queue.hidden == {}


async def test_a_message_that_is_not_a_document_id_is_dropped(
    session_factory: async_sessionmaker[AsyncSession], dataset: Dataset
) -> None:
    pipeline = Pipeline(dataset, session_factory, [pick(dataset)])
    queue = MemoryQueue()
    await queue.send("not-a-uuid")
    await queue.send("00000000-0000-0000-0000-000000000000")  # no such document

    await _handle_next(queue, pipeline)
    await _handle_next(queue, pipeline)

    assert queue.hidden == {}


async def test_the_worker_loop_drains_the_queue_and_stops_when_asked(
    session_factory: async_sessionmaker[AsyncSession], dataset: Dataset
) -> None:
    clean, wrong_iban = pick(dataset), pick(dataset, case="wrong_iban")
    pipeline = Pipeline(dataset, session_factory, [clean, wrong_iban])
    queue = MemoryQueue()
    ids = [await pipeline.ingest(clean), await pipeline.ingest(wrong_iban)]
    for document_id in ids:
        await queue.send(str(document_id))
    stop = asyncio.Event()

    async def stop_when_empty() -> None:
        while queue.waiting or queue.hidden:
            await asyncio.sleep(0.01)
        stop.set()

    await asyncio.gather(
        work(queue, pipeline.graph, session_factory, pipeline.settings, stop, idle_seconds=0.01),
        stop_when_empty(),
    )

    assert [await _status(session_factory, document_id) for document_id in ids] == [
        DocumentStatus.AUTO_APPROVED.value,
        DocumentStatus.IN_REVIEW.value,
    ]
