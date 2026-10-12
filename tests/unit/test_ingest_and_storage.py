from decimal import Decimal
from pathlib import Path

import pytest

from app.observability.prices import call_cost
from app.storage.local import LocalStorage, MemoryStorage
from app.workflow.ingest import RejectedUpload, check_upload

PDF = b"%PDF-1.4 minimal"


def test_pdf_within_the_limit_is_accepted() -> None:
    check_upload("factuur.PDF", PDF, max_bytes=1024)


@pytest.mark.parametrize(
    ("filename", "content"),
    [("factuur.docx", PDF), ("factuur.pdf", b"PK\x03\x04 not a pdf"), ("factuur", PDF)],
)
def test_non_pdf_is_refused_with_a_clear_message(filename: str, content: bytes) -> None:
    with pytest.raises(RejectedUpload, match="Alleen pdf-bestanden"):
        check_upload(filename, content, max_bytes=1024)


def test_oversized_file_is_refused_with_the_limit_in_the_message() -> None:
    with pytest.raises(RejectedUpload, match="limiet van 2 MB"):
        check_upload("groot.pdf", PDF + b"x" * (2 * 1024 * 1024), max_bytes=2 * 1024 * 1024)


async def test_local_storage_round_trip_and_path_safety(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path / "uploads")

    await storage.save("abc.pdf", PDF)

    assert await storage.load("abc.pdf") == PDF
    with pytest.raises(ValueError, match="outside"):
        await storage.save("../escape.pdf", PDF)


async def test_memory_storage_round_trip() -> None:
    storage = MemoryStorage()
    await storage.save("k", PDF)
    assert await storage.load("k") == PDF


def test_call_cost() -> None:
    read = call_cost(model="prebuilt-read", pages=2, input_tokens=0, output_tokens=0)
    chat = call_cost(model="gpt-4.1", pages=0, input_tokens=2000, output_tokens=500)

    assert read == Decimal("0.00264")
    assert chat == Decimal("0.00845")
    assert call_cost(model="fake-chat", pages=0, input_tokens=10, output_tokens=10) is None
