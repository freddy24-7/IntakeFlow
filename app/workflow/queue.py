"""The work queue between the web application and the worker.

An upload puts the document's id on the queue. A worker takes it off, runs the
workflow and deletes the message when the document has a result. A message that
is not deleted becomes visible again after a while, so a worker that dies in
the middle of a document does not lose it. This replaces the Redis Streams
consumer group that Muni Mailbox built by hand.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from azure.identity.aio import DefaultAzureCredential
from azure.storage.queue.aio import QueueClient


@dataclass(frozen=True)
class QueueMessage:
    id: str
    receipt: str
    body: str
    dequeue_count: int


class JobQueue(Protocol):
    async def send(self, body: str) -> None: ...

    async def receive(self, *, limit: int, visibility_timeout: int) -> Sequence[QueueMessage]:
        """Take up to `limit` messages. Each stays hidden from other workers for
        `visibility_timeout` seconds and comes back unless it is deleted."""
        ...

    async def delete(self, message: QueueMessage) -> None: ...


class AzureQueue:
    def __init__(self, client: Any, credential: Any = None) -> None:
        self._client = client
        self._credential = credential

    @classmethod
    def connect(cls, *, account_url: str, queue: str) -> "AzureQueue":
        credential = DefaultAzureCredential()
        return cls(QueueClient(account_url, queue, credential=credential), credential)

    async def send(self, body: str) -> None:
        await self._client.send_message(body)

    async def receive(self, *, limit: int, visibility_timeout: int) -> Sequence[QueueMessage]:
        pages = self._client.receive_messages(
            max_messages=limit, visibility_timeout=visibility_timeout
        )
        return [QueueMessage(m.id, m.pop_receipt, m.content, m.dequeue_count) async for m in pages]

    async def delete(self, message: QueueMessage) -> None:
        await self._client.delete_message(message.id, message.receipt)

    async def close(self) -> None:
        await self._client.close()
        if self._credential is not None:
            await self._credential.close()


@dataclass
class MemoryQueue:
    """For tests. A received message stays hidden until `release` is called,
    which stands in for the visibility timeout running out."""

    waiting: list[QueueMessage] = field(default_factory=list)
    hidden: dict[str, QueueMessage] = field(default_factory=dict)

    async def send(self, body: str) -> None:
        self.waiting.append(QueueMessage(uuid.uuid4().hex, "", body, 0))

    async def receive(self, *, limit: int, visibility_timeout: int) -> Sequence[QueueMessage]:
        taken, self.waiting = self.waiting[:limit], self.waiting[limit:]
        received = []
        for message in taken:
            seen = QueueMessage(
                message.id, uuid.uuid4().hex, message.body, message.dequeue_count + 1
            )
            self.hidden[seen.id] = seen
            received.append(seen)
        return received

    async def delete(self, message: QueueMessage) -> None:
        self.hidden.pop(message.id, None)

    def release(self) -> None:
        self.waiting += self.hidden.values()
        self.hidden = {}


class QueueDispatcher:
    """What the web application does with an upload when a queue is configured."""

    def __init__(self, queue: JobQueue) -> None:
        self._queue = queue

    async def dispatch(self, document_id: uuid.UUID) -> None:
        await self._queue.send(str(document_id))
