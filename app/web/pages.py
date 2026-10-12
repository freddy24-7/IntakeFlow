"""The server-rendered pages: role picker, upload, review queue, review and dashboard."""

import asyncio
import uuid
from datetime import date
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.prompts import ANSWER_CONTRACT, load_prompt
from app.agents.schema import FIELD_KINDS
from app.audit import log as audit
from app.auth.demo import (
    CONTRACT_MANAGER,
    COOKIE,
    FINANCE_CLERK,
    HOME,
    ROLES,
    TEAM_LEAD,
    current_role,
    require_role,
)
from app.config import Settings, get_settings
from app.db.models import Document, DocumentStatus, RoutingDecision
from app.observability.dashboard import load_dashboard
from app.rag.answer import answer_question
from app.review import service as review
from app.review.service import ReviewError
from app.storage.interfaces import Storage
from app.web import labels, preview
from app.web.deps import get_dispatcher, get_services, get_session, get_storage
from app.web.upload import ingest_files
from app.workflow.dispatch import Dispatcher
from app.workflow.routing_steps import REASON_NOT_AN_INVOICE
from app.workflow.steps import Services

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
templates.env.globals.update(
    roles=ROLES,
    field_labels=labels.FIELD_LABELS,
    flag_labels=labels.FLAG_LABELS,
    status_labels=labels.STATUS_LABELS,
    type_labels=labels.TYPE_LABELS,
    reason_label=labels.reason_label,
)

Session = Annotated[AsyncSession, Depends(get_session)]
Clerk = Annotated[str, Depends(require_role(FINANCE_CLERK))]
Files = Annotated[Storage, Depends(get_storage)]


def _page(request: Request, name: str, **context: Any) -> HTMLResponse:
    return templates.TemplateResponse(request, name, {"role": current_role(request), **context})


@router.get("/")
async def pick_role(request: Request) -> HTMLResponse:
    return _page(request, "pick_role.html")


@router.post("/login")
async def login(role: Annotated[str, Form()]) -> RedirectResponse:
    if role not in ROLES:
        raise HTTPException(status_code=400, detail="Onbekende rol.")
    response = RedirectResponse(HOME[role], status_code=303)
    response.set_cookie(COOKIE, role, httponly=True, samesite="lax")
    return response


@router.get("/logout")
async def logout() -> RedirectResponse:
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(COOKIE)
    return response


@router.get("/upload")
async def upload_page(request: Request, role: Clerk) -> HTMLResponse:
    return _page(request, "upload.html")


@router.post("/upload")
async def upload(
    request: Request,
    role: Clerk,
    files: list[UploadFile],
    session: Session,
    storage: Annotated[Storage, Depends(get_storage)],
    dispatcher: Annotated[Dispatcher, Depends(get_dispatcher)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> HTMLResponse:
    results = await ingest_files(files, session, storage, dispatcher, settings)
    return _page(request, "_upload_results.html", results=results)


async def _queue(session: AsyncSession) -> dict[str, Any]:
    """Documents waiting for a person, oldest first, each with its reasons."""
    waiting = (
        (
            await session.execute(
                select(Document)
                .where(
                    Document.origin == "upload",
                    Document.status.in_(
                        [DocumentStatus.IN_REVIEW.value, DocumentStatus.FAILED.value]
                    ),
                )
                .order_by(Document.created_at, Document.filename)
            )
        )
        .scalars()
        .all()
    )
    reasons: dict[uuid.UUID, list[str]] = {}
    if waiting:
        decisions = await session.execute(
            select(RoutingDecision.document_id, RoutingDecision.reasons).where(
                RoutingDecision.document_id.in_([document.id for document in waiting])
            )
        )
        reasons = {document_id: list(why) for document_id, why in decisions}
    in_progress = (
        await session.execute(
            select(Document.id).where(
                Document.origin == "upload",
                Document.status.in_(
                    [DocumentStatus.RECEIVED.value, DocumentStatus.PROCESSING.value]
                ),
                Document.document_type.is_distinct_from("contract"),
            )
        )
    ).all()
    rows = [
        {"document": document, "reasons": reasons.get(document.id, [REASON_NOT_AN_INVOICE])}
        for document in waiting
    ]
    return {"rows": rows, "in_progress": len(in_progress)}


@router.get("/queue")
async def queue(request: Request, role: Clerk, session: Session) -> HTMLResponse:
    return _page(
        request, "queue.html", **await _queue(session), notice=request.query_params.get("notice")
    )


@router.get("/queue/rows")
async def queue_rows(request: Request, role: Clerk, session: Session) -> HTMLResponse:
    return _page(request, "_queue_rows.html", **await _queue(session))


async def _review_page(
    request: Request,
    session: AsyncSession,
    storage: Storage,
    document_id: uuid.UUID,
    *,
    values: dict[str, str] | None = None,
    errors: dict[str, str] | None = None,
    message: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    try:
        case = await review.load_case(session, document_id)
    except ReviewError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    if values is None and case.invoice is not None:
        values = {name: case.invoice.fields[name].value or "" for name in FIELD_KINDS}
    pages = 0
    if case.document.storage_key is not None:
        content = await storage.load(case.document.storage_key)
        pages = await asyncio.to_thread(preview.page_count, content)
    response = _page(
        request,
        "review.html",
        case=case,
        pages=pages,
        values=values or {},
        errors=errors or {},
        message=message,
        open=case.document.status == DocumentStatus.IN_REVIEW.value,
    )
    response.status_code = status_code
    return response


@router.get("/review/{document_id}")
async def review_page(
    request: Request, role: Clerk, session: Session, storage: Files, document_id: uuid.UUID
) -> HTMLResponse:
    return await _review_page(request, session, storage, document_id)


async def _submitted(request: Request) -> dict[str, str]:
    form = await request.form()
    return {name: str(form.get(name, "")) for name in FIELD_KINDS}


@router.post("/review/{document_id}/check")
async def review_check(
    request: Request,
    role: Clerk,
    session: Session,
    document_id: uuid.UUID,
    settings: Annotated[Settings, Depends(get_settings)],
) -> HTMLResponse:
    """Validate the form as it is now and return the outcome as a fragment."""
    try:
        corrected, failures = await review.check(
            session, document_id, await _submitted(request), settings=settings, today=date.today()
        )
    except ReviewError as error:
        return _page(request, "_check_result.html", message=str(error), failures=[], errors={})
    return _page(
        request,
        "_check_result.html",
        failures=failures,
        errors=corrected.errors,
        corrections=corrected.corrections,
        message=None,
    )


@router.post("/review/{document_id}/approve")
async def review_approve(
    request: Request,
    role: Clerk,
    session: Session,
    storage: Files,
    document_id: uuid.UUID,
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    submitted = await _submitted(request)
    try:
        await review.approve(
            session, document_id, submitted, role=role, settings=settings, today=date.today()
        )
    except ReviewError as error:
        await session.rollback()
        case = await review.load_case(session, document_id)
        errors = review.apply_corrections(case.invoice, submitted).errors if case.invoice else {}
        return await _review_page(
            request,
            session,
            storage,
            document_id,
            values=submitted,
            errors=errors,
            message=str(error),
            status_code=422,
        )
    await session.commit()
    return RedirectResponse("/queue?notice=approved", status_code=303)


@router.post("/review/{document_id}/reject")
async def review_reject(
    request: Request,
    role: Clerk,
    session: Session,
    storage: Files,
    document_id: uuid.UUID,
    reason: Annotated[str, Form()] = "",
) -> Response:
    try:
        await review.reject(session, document_id, role=role, reason=reason)
    except ReviewError as error:
        await session.rollback()
        return await _review_page(
            request, session, storage, document_id, message=str(error), status_code=422
        )
    await session.commit()
    return RedirectResponse("/queue?notice=rejected", status_code=303)


@router.get("/documents/{document_id}/file")
async def document_file(
    role: Clerk,
    session: Session,
    storage: Annotated[Storage, Depends(get_storage)],
    document_id: uuid.UUID,
) -> Response:
    document = await session.get(Document, document_id)
    if document is None or document.storage_key is None:
        raise HTTPException(status_code=404, detail="Dit document bestaat niet.")
    content = await storage.load(document.storage_key)
    return Response(content, media_type="application/pdf")


@router.get("/documents/{document_id}/pages/{number}.png")
async def document_page(
    role: Clerk,
    session: Session,
    storage: Annotated[Storage, Depends(get_storage)],
    document_id: uuid.UUID,
    number: int,
) -> Response:
    document = await session.get(Document, document_id)
    if document is None or document.storage_key is None:
        raise HTTPException(status_code=404, detail="Dit document bestaat niet.")
    content = await storage.load(document.storage_key)
    image = await asyncio.to_thread(preview.render_page, content, number)
    if image is None:
        raise HTTPException(status_code=404, detail="Deze pagina bestaat niet.")
    return Response(image, media_type="image/png")


@router.get("/dashboard")
async def dashboard(
    request: Request,
    role: Annotated[str, Depends(require_role(TEAM_LEAD))],
    session: Session,
) -> HTMLResponse:
    return _page(request, "dashboard.html", data=await load_dashboard(session))


Manager = Annotated[str, Depends(require_role(CONTRACT_MANAGER))]


async def _indexed_contracts(session: AsyncSession) -> int:
    count: int = (
        await session.execute(
            select(func.count())
            .select_from(Document)
            .where(Document.origin == "upload", Document.status == DocumentStatus.INDEXED.value)
        )
    ).scalar_one()
    return count


@router.get("/contracts")
async def contracts(request: Request, role: Manager, session: Session) -> HTMLResponse:
    return _page(request, "contracts.html", indexed=await _indexed_contracts(session))


@router.post("/contracts/ask")
async def contracts_ask(
    request: Request,
    role: Manager,
    session: Session,
    question: Annotated[str, Form()],
    services: Annotated[Services | None, Depends(get_services)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> HTMLResponse:
    """Answer a question about the contract archive, as a fragment for the page."""
    asked = question.strip()
    if not asked:
        return _page(request, "_answer.html", message="Stel een vraag.")
    if services is None or services.search is None:
        return _page(request, "_answer.html", message="Zoeken in contracten is niet ingesteld.")
    assert services.embedder is not None
    assert services.answerer is not None
    answer = await answer_question(
        asked,
        index=services.search,
        embedder=services.embedder,
        model=services.answerer,
        prompt=load_prompt(ANSWER_CONTRACT),
        top=settings.search_top_k,
    )
    # Rule 8: what happened, not what was asked or answered.
    await audit.append(
        session,
        step="question_answered",
        payload={
            "found": answer.found,
            "citations": len(answer.citations),
            "dropped": len(answer.dropped),
        },
    )
    await session.commit()
    return _page(request, "_answer.html", answer=answer, question=asked, message=None)
