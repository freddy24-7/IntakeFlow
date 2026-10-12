"""Stage 6 adapters without Azure: Blob Storage, the Azure queue and telemetry."""

from pathlib import Path
from typing import Any

from app.config import Settings
from app.observability.telemetry import configure_telemetry
from app.storage.blob import BlobStorage
from app.storage.local import LocalStorage
from app.workflow.queue import AzureQueue
from app.workflow.services import build_storage, checkpoint_url


class _Download:
    def __init__(self, content: bytes) -> None:
        self._content = content

    async def readall(self) -> bytes:
        return self._content


class _Container:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}
        self.overwrite: list[bool] = []

    async def upload_blob(self, name: str, data: bytes, overwrite: bool) -> None:
        self.blobs[name] = data
        self.overwrite.append(overwrite)

    async def download_blob(self, name: str) -> _Download:
        return _Download(self.blobs[name])


async def test_blob_storage_round_trip_and_safe_to_repeat() -> None:
    container = _Container()
    storage = BlobStorage(container)

    await storage.save("abc.pdf", b"%PDF-1")
    await storage.save("abc.pdf", b"%PDF-2")  # a repeated step overwrites, it does not fail

    assert await storage.load("abc.pdf") == b"%PDF-2"
    assert container.overwrite == [True, True]


class _Message:
    def __init__(self, body: str) -> None:
        self.id, self.pop_receipt, self.content, self.dequeue_count = "m1", "r1", body, 2


class _QueueClient:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.deleted: list[tuple[str, str]] = []
        self.options: dict[str, Any] = {}

    async def send_message(self, body: str) -> None:
        self.sent.append(body)

    def receive_messages(self, **options: Any) -> Any:
        self.options = options

        async def pages() -> Any:
            for body in self.sent:
                yield _Message(body)

        return pages()

    async def delete_message(self, message_id: str, receipt: str) -> None:
        self.deleted.append((message_id, receipt))


async def test_azure_queue_maps_messages_and_deletes_by_receipt() -> None:
    client = _QueueClient()
    queue = AzureQueue(client)

    await queue.send("doc-id")
    [message] = await queue.receive(limit=1, visibility_timeout=600)
    await queue.delete(message)

    assert (message.body, message.dequeue_count) == ("doc-id", 2)
    assert client.options == {"max_messages": 1, "visibility_timeout": 600}
    assert client.deleted == [("m1", "r1")]


def test_telemetry_is_off_without_a_connection_string() -> None:
    settings = Settings(_env_file=None, database_url="unused")

    assert configure_telemetry(settings, service_name="test") is False


def test_storage_and_checkpoint_settings(tmp_path: Path) -> None:
    local = Settings(_env_file=None, database_url="unused", storage_dir=tmp_path)

    assert build_storage(local) == LocalStorage(tmp_path)
    assert (
        checkpoint_url("postgresql+asyncpg://user:secret@db:5432/intakeflow")
        == "postgresql://user:secret@db:5432/intakeflow"
    )
    assert (
        checkpoint_url("postgresql+asyncpg://user:secret@db.example:5432/intakeflow?ssl=require")
        == "postgresql://user:secret@db.example:5432/intakeflow?sslmode=require"
    )
