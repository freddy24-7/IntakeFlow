"""Upload endpoint (PRD F1): one or more PDFs in, one result per file out."""

from typing import Annotated

from fastapi import APIRouter, Depends, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.storage.interfaces import Storage
from app.web.deps import get_dispatcher, get_session, get_storage
from app.workflow.dispatch import Dispatcher
from app.workflow.ingest import RejectedUpload, ingest

router = APIRouter()


class UploadResult(BaseModel):
    filename: str
    accepted: bool
    document_id: str | None = None
    message: str | None = None


async def ingest_files(
    files: list[UploadFile],
    session: AsyncSession,
    storage: Storage,
    dispatcher: Dispatcher,
    settings: Settings,
) -> list[UploadResult]:
    """A refused file does not stop the others."""
    results = []
    for file in files:
        filename = file.filename or "naamloos"
        # Read one byte past the limit: enough to know the file is too large
        # without loading all of it.
        content = await file.read(settings.max_upload_bytes + 1)
        try:
            document = await ingest(
                session,
                storage,
                filename=filename,
                content=content,
                max_bytes=settings.max_upload_bytes,
            )
        except RejectedUpload as rejection:
            results.append(UploadResult(filename=filename, accepted=False, message=str(rejection)))
            continue
        await session.commit()
        await dispatcher.dispatch(document.id)
        results.append(UploadResult(filename=filename, accepted=True, document_id=str(document.id)))
    return results


@router.post("/documents")
async def upload_documents(
    files: list[UploadFile],
    session: Annotated[AsyncSession, Depends(get_session)],
    storage: Annotated[Storage, Depends(get_storage)],
    dispatcher: Annotated[Dispatcher, Depends(get_dispatcher)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> list[UploadResult]:
    """JSON upload endpoint (PRD F1): one or more PDFs in, one result per file out."""
    return await ingest_files(files, session, storage, dispatcher, settings)
