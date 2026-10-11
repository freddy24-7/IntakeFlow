"""Ingestion (PRD F1): check an uploaded file, store it and register the document."""

import hashlib
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log as audit
from app.db.models import Document
from app.storage.interfaces import Storage

STEP_UPLOADED = "uploaded"
PDF_MAGIC = b"%PDF-"


class RejectedUpload(Exception):
    """The file is refused. The message is shown to the person who uploaded it."""


def check_upload(filename: str, content: bytes, max_bytes: int) -> None:
    if not filename.lower().endswith(".pdf") or not content.startswith(PDF_MAGIC):
        raise RejectedUpload("Alleen pdf-bestanden worden geaccepteerd.")
    if len(content) > max_bytes:
        limit_mb = max_bytes // (1024 * 1024)
        raise RejectedUpload(f"Het bestand is groter dan de limiet van {limit_mb} MB.")


async def ingest(
    session: AsyncSession, storage: Storage, *, filename: str, content: bytes, max_bytes: int
) -> Document:
    """Store the file and create the document. The caller commits."""
    check_upload(filename, content, max_bytes)
    document_id = uuid.uuid4()
    storage_key = f"{document_id}.pdf"
    await storage.save(storage_key, content)
    document = Document(
        id=document_id,
        filename=filename[:255],
        content_sha256=hashlib.sha256(content).hexdigest(),
        storage_key=storage_key,
        size_bytes=len(content),
    )
    session.add(document)
    await session.flush()
    # Rule 8: the file name can contain a supplier name, so it stays out of the audit log.
    await audit.append(
        session, step=STEP_UPLOADED, document_id=document.id, payload={"size_bytes": len(content)}
    )
    return document
