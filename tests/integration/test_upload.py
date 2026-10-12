"""The upload endpoint (PRD F1), with the database real and everything else fake."""

import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.db.models import AuditRecord, Document, DocumentStatus
from app.main import app
from app.storage.local import MemoryStorage
from app.web.deps import get_dispatcher, get_session, get_storage

PDF = b"%PDF-1.4 synthetic"
LIMIT = 1024


class RecordingDispatcher:
    def __init__(self) -> None:
        self.dispatched: list[uuid.UUID] = []

    async def dispatch(self, document_id: uuid.UUID) -> None:
        self.dispatched.append(document_id)


@pytest.fixture
def storage() -> MemoryStorage:
    return MemoryStorage()


@pytest.fixture
def dispatcher() -> RecordingDispatcher:
    return RecordingDispatcher()


@pytest.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession],
    storage: MemoryStorage,
    dispatcher: RecordingDispatcher,
) -> AsyncIterator[AsyncClient]:
    async def _session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as db_session:
            yield db_session

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_dispatcher] = lambda: dispatcher
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, database_url="unused", max_upload_bytes=LIMIT
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http
    app.dependency_overrides.clear()


async def test_pdf_is_stored_registered_audited_and_dispatched(
    client: AsyncClient,
    session: AsyncSession,
    storage: MemoryStorage,
    dispatcher: RecordingDispatcher,
) -> None:
    response = await client.post(
        "/documents", files=[("files", ("factuur.pdf", PDF, "application/pdf"))]
    )

    assert response.status_code == 200
    [result] = response.json()
    assert result["accepted"] is True
    document = await session.get(Document, uuid.UUID(result["document_id"]))
    assert document is not None
    assert (document.filename, document.size_bytes, document.status) == (
        "factuur.pdf",
        len(PDF),
        DocumentStatus.RECEIVED.value,
    )
    assert document.storage_key is not None
    assert storage.files[document.storage_key] == PDF
    assert dispatcher.dispatched == [document.id]
    audit_record = (await session.execute(select(AuditRecord))).scalar_one()
    assert (audit_record.step, audit_record.payload) == ("uploaded", {"size_bytes": len(PDF)})


async def test_refused_files_do_not_stop_the_others(
    client: AsyncClient, session: AsyncSession, dispatcher: RecordingDispatcher
) -> None:
    response = await client.post(
        "/documents",
        files=[
            ("files", ("brief.docx", b"PK\x03\x04", "application/msword")),
            ("files", ("groot.pdf", PDF + b"x" * LIMIT, "application/pdf")),
            ("files", ("goed.pdf", PDF, "application/pdf")),
        ],
    )

    results = response.json()
    assert [result["accepted"] for result in results] == [False, False, True]
    assert "Alleen pdf-bestanden" in results[0]["message"]
    assert "groter dan de limiet" in results[1]["message"]
    assert results[0]["document_id"] is None
    documents = (await session.execute(select(Document))).scalars().all()
    assert [document.filename for document in documents] == ["goed.pdf"]
    assert len(dispatcher.dispatched) == 1
