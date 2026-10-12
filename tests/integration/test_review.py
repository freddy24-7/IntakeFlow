"""Stage 4: review, corrections stored next to the extraction, and the pages."""

import re
import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from synthetic.build import Dataset
from synthetic.truth import DocumentTruth

from app.agents.schema import FIELD_KINDS, ExtractedInvoice
from app.auth.demo import COOKIE
from app.config import Settings, get_settings
from app.db.models import AuditRecord, Document, DocumentStatus, Extraction, Review
from app.main import app
from app.review import service as review
from app.review.service import ReviewError
from app.validation.purchase_orders import upsert_purchase_orders
from app.web.deps import get_dispatcher, get_session, get_storage
from tests.integration.pipeline import TODAY, Pipeline, pick

SETTINGS = Settings(_env_file=None, database_url="unused")


class Case:
    """One document that the pipeline sent to review, ready to be reviewed."""

    def __init__(self, pipeline: Pipeline, truth: DocumentTruth, document_id: uuid.UUID) -> None:
        self.pipeline = pipeline
        self.truth = truth
        self.document_id = document_id

    async def form(self, session: AsyncSession) -> dict[str, str]:
        """The form as the review page first shows it: the extracted values."""
        case = await review.load_case(session, self.document_id)
        assert case.invoice is not None
        return {name: case.invoice.fields[name].value or "" for name in FIELD_KINDS}


async def _case(
    dataset: Dataset, session_factory: async_sessionmaker[AsyncSession], hard_case: str
) -> Case:
    truth = pick(dataset, case=hard_case)
    pipeline = Pipeline(dataset, session_factory, [truth])
    return Case(pipeline, truth, await pipeline.process(truth))


async def _document(session: AsyncSession, document_id: uuid.UUID) -> Document:
    document = await session.get(Document, document_id, populate_existing=True)
    assert document is not None
    return document


async def _erp_rows(session: AsyncSession) -> list[tuple[str, str]]:
    rows = await session.execute(text("SELECT invoice_number, total::text FROM erp_entries"))
    return [(number, total) for number, total in rows]


async def test_approving_unchanged_books_the_document_and_records_open_checks(
    session_factory: async_sessionmaker[AsyncSession], session: AsyncSession, dataset: Dataset
) -> None:
    case = await _case(dataset, session_factory, "missing_po")

    stored = await review.approve(
        session,
        case.document_id,
        await case.form(session),
        role="finance_clerk",
        settings=SETTINGS,
        today=TODAY,
    )
    await session.commit()

    assert (stored.action, stored.unchanged, stored.corrections) == ("approved", True, {})
    # The reviewer is in charge: the open check is recorded, not enforced.
    assert stored.failures_at_approval == ["po_missing"]
    assert (await _document(session, case.document_id)).status == DocumentStatus.APPROVED.value
    assert case.truth.invoice is not None
    assert await _erp_rows(session) == [
        (case.truth.invoice.invoice_number, f"{case.truth.invoice.total:.2f}")
    ]


async def test_a_correction_is_stored_next_to_the_extraction_not_over_it(
    session_factory: async_sessionmaker[AsyncSession], session: AsyncSession, dataset: Dataset
) -> None:
    """Rule 5."""
    case = await _case(dataset, session_factory, "wrong_iban")
    right_iban = dataset.plans[case.truth.doc_id].supplier.iban
    form = await case.form(session)
    wrong_iban = form["iban"]
    assert wrong_iban != right_iban
    grouped = " ".join(right_iban[index : index + 4] for index in range(0, len(right_iban), 4))

    stored = await review.approve(
        session,
        case.document_id,
        {**form, "iban": grouped},  # typed with spaces, as printed
        role="finance_clerk",
        settings=SETTINGS,
        today=TODAY,
    )
    await session.commit()

    assert stored.corrections == {"iban": right_iban}
    assert stored.unchanged is False
    assert stored.failures_at_approval == []
    extraction = (await session.execute(select(Extraction))).scalar_one()
    assert stored.extraction_id == extraction.id
    untouched = ExtractedInvoice.model_validate(extraction.data)
    assert untouched.fields["iban"].value == wrong_iban
    record = (
        await session.execute(select(AuditRecord).where(AuditRecord.step == "reviewed"))
    ).scalar_one()
    assert record.payload == {
        "action": "approved",
        "role": "finance_clerk",
        "corrected_fields": ["iban"],
        "failures": [],
    }
    assert right_iban not in str(record.payload)  # rule 8: field names, not values


async def test_dutch_amounts_and_dates_are_accepted_as_typed(
    session_factory: async_sessionmaker[AsyncSession], session: AsyncSession, dataset: Dataset
) -> None:
    case = await _case(dataset, session_factory, "totals_mismatch")
    extracted = (await review.load_case(session, case.document_id)).invoice
    assert extracted is not None
    form = await case.form(session)

    corrected = review.apply_corrections(
        extracted, {**form, "total": "€ 1.234,56", "due_date": "31-12-2026"}
    )

    assert corrected.errors == {}
    assert corrected.corrections == {"total": "1234.56", "due_date": "2026-12-31"}
    assert all(field.flags == [] for field in corrected.invoice.fields.values())
    assert extracted.fields["total"].value != "1234.56"  # the original object is not changed


async def test_unreadable_input_stops_the_approval(
    session_factory: async_sessionmaker[AsyncSession], session: AsyncSession, dataset: Dataset
) -> None:
    case = await _case(dataset, session_factory, "missing_po")
    form = {**await case.form(session), "total": "veel"}

    corrected, _ = await review.check(
        session, case.document_id, form, settings=SETTINGS, today=TODAY
    )
    assert list(corrected.errors) == ["total"]
    with pytest.raises(ReviewError, match="leesbaar"):
        await review.approve(
            session, case.document_id, form, role="finance_clerk", settings=SETTINGS, today=TODAY
        )
    await session.rollback()

    assert (await _document(session, case.document_id)).status == DocumentStatus.IN_REVIEW.value
    assert await _erp_rows(session) == []


async def test_rejecting_needs_a_reason_and_books_nothing(
    session_factory: async_sessionmaker[AsyncSession], session: AsyncSession, dataset: Dataset
) -> None:
    case = await _case(dataset, session_factory, "wrong_iban")

    with pytest.raises(ReviewError, match="reden"):
        await review.reject(session, case.document_id, role="finance_clerk", reason="  ")
    stored = await review.reject(
        session,
        case.document_id,
        role="finance_clerk",
        reason="IBAN klopt niet, leverancier gebeld",
    )
    await session.commit()

    assert (stored.action, stored.reason) == ("rejected", "IBAN klopt niet, leverancier gebeld")
    assert (await _document(session, case.document_id)).status == DocumentStatus.REJECTED.value
    assert await _erp_rows(session) == []
    payloads = (await session.execute(select(AuditRecord.payload))).scalars().all()
    assert "leverancier gebeld" not in str(payloads)  # free text stays out of the audit log


async def test_a_document_is_reviewed_once(
    session_factory: async_sessionmaker[AsyncSession], session: AsyncSession, dataset: Dataset
) -> None:
    case = await _case(dataset, session_factory, "missing_po")
    form = await case.form(session)
    await review.approve(
        session, case.document_id, form, role="finance_clerk", settings=SETTINGS, today=TODAY
    )
    await session.commit()

    with pytest.raises(ReviewError, match="wacht niet"):
        await review.approve(
            session, case.document_id, form, role="finance_clerk", settings=SETTINGS, today=TODAY
        )
    with pytest.raises(ReviewError, match="wacht niet"):
        await review.reject(session, case.document_id, role="finance_clerk", reason="toch niet")
    assert len(await _erp_rows(session)) == 1


async def test_a_duplicate_cannot_be_approved_into_the_erp(
    session_factory: async_sessionmaker[AsyncSession], session: AsyncSession, dataset: Dataset
) -> None:
    duplicate = next(
        doc
        for doc in dataset.documents
        if doc.hard_cases == ["duplicate"]
        and not next(d for d in dataset.documents if d.doc_id == doc.duplicate_of).scanned
    )
    original = next(doc for doc in dataset.documents if doc.doc_id == duplicate.duplicate_of)
    pipeline = Pipeline(dataset, session_factory, [original, duplicate])
    await pipeline.process(original)
    case = Case(pipeline, duplicate, await pipeline.process(duplicate))

    with pytest.raises(ReviewError, match="al geboekt"):
        await review.approve(
            session,
            case.document_id,
            await case.form(session),
            role="finance_clerk",
            settings=SETTINGS,
            today=TODAY,
        )
    await session.rollback()

    assert len(await _erp_rows(session)) == 1
    assert (await _document(session, case.document_id)).status == DocumentStatus.IN_REVIEW.value


# The pages


@pytest.fixture
async def client(session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncClient]:
    async def _session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as db_session:
            yield db_session

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_settings] = lambda: SETTINGS
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http
    app.dependency_overrides.clear()


def _as(client: AsyncClient, role: str) -> None:
    client.cookies.set(COOKIE, role)


async def test_pages_need_a_role_and_the_right_one(client: AsyncClient) -> None:
    picker = await client.get("/")
    assert "Kies een rol" in picker.text

    nobody = await client.get("/queue")
    assert (nobody.status_code, nobody.headers["location"]) == (303, "/")

    login = await client.post("/login", data={"role": "team_lead"})
    assert (login.status_code, login.headers["location"]) == (303, "/dashboard")
    assert (await client.get("/queue")).status_code == 403
    assert (await client.post("/login", data={"role": "admin"})).status_code == 400


async def test_queue_review_check_and_approve_through_the_pages(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    dataset: Dataset,
) -> None:
    case = await _case(dataset, session_factory, "wrong_iban")
    app.dependency_overrides[get_storage] = lambda: case.pipeline.services.storage
    _as(client, "finance_clerk")

    queue = await client.get("/queue")
    assert case.truth.filename in queue.text
    assert "IBAN is ongeldig (controlegetal)" in queue.text
    assert f"/review/{case.document_id}" in queue.text

    page = await client.get(f"/review/{case.document_id}")
    form = await case.form(session)
    assert page.status_code == 200
    assert f'value="{form["iban"]}"' in page.text
    assert "IBAN is ongeldig (controlegetal)" in page.text
    assert "Goedkeuren en boeken" in page.text

    assert f"/documents/{case.document_id}/pages/1.png" in page.text
    image = await client.get(f"/documents/{case.document_id}/pages/1.png")
    assert image.headers["content-type"] == "image/png"
    assert image.content.startswith(b"\x89PNG")
    assert (await client.get(f"/documents/{case.document_id}/pages/2.png")).status_code == 404

    pdf = await client.get(f"/documents/{case.document_id}/file")
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")

    still_wrong = await client.post(f"/review/{case.document_id}/check", data=form)
    assert "IBAN is ongeldig" in still_wrong.text
    assert "U kunt toch goedkeuren" in still_wrong.text
    right = {**form, "iban": dataset.plans[case.truth.doc_id].supplier.iban}
    fixed = await client.post(f"/review/{case.document_id}/check", data=right)
    assert "slagen alle controles" in fixed.text

    unreadable = await client.post(
        f"/review/{case.document_id}/approve", data={**form, "total": "veel"}
    )
    assert unreadable.status_code == 422
    assert "Niet alle velden zijn leesbaar ingevuld" in unreadable.text
    assert 'value="veel"' in unreadable.text  # the reviewer's input is kept

    approved = await client.post(f"/review/{case.document_id}/approve", data=right)
    assert (approved.status_code, approved.headers["location"]) == (
        303,
        "/queue?notice=approved",
    )
    assert (await _document(session, case.document_id)).status == DocumentStatus.APPROVED.value
    stored = (await session.execute(select(Review))).scalar_one()
    assert list(stored.corrections) == ["iban"]

    after = await client.get("/queue?notice=approved")
    assert "goedgekeurd en geboekt" in after.text
    assert "Er wacht niets op beoordeling" in after.text
    closed = await client.get(f"/review/{case.document_id}")
    assert "Goedkeuren en boeken" not in closed.text


async def test_reject_through_the_page(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    dataset: Dataset,
) -> None:
    case = await _case(dataset, session_factory, "missing_po")
    app.dependency_overrides[get_storage] = lambda: case.pipeline.services.storage
    _as(client, "finance_clerk")

    no_reason = await client.post(f"/review/{case.document_id}/reject", data={"reason": ""})
    assert no_reason.status_code == 422
    assert "Geef een reden" in no_reason.text

    rejected = await client.post(
        f"/review/{case.document_id}/reject", data={"reason": "Geen inkooporder"}
    )
    assert rejected.headers["location"] == "/queue?notice=rejected"
    assert (await _document(session, case.document_id)).status == DocumentStatus.REJECTED.value


async def test_other_mail_can_only_be_dismissed(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    dataset: Dataset,
) -> None:
    truth = pick(dataset, doc_type="other")
    pipeline = Pipeline(dataset, session_factory, [truth])
    document_id = await pipeline.process(truth)
    app.dependency_overrides[get_storage] = lambda: pipeline.services.storage
    _as(client, "finance_clerk")

    queue = await client.get("/queue/rows")
    assert "Geen factuur of creditnota" in queue.text
    page = await client.get(f"/review/{document_id}")
    assert "Afwijzen" in page.text
    assert "Goedkeuren en boeken" not in page.text
    refused = await client.post(f"/review/{document_id}/approve", data={})
    assert refused.status_code == 422


async def test_upload_page_and_dashboard(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    dataset: Dataset,
) -> None:
    clean, needs_review = pick(dataset), pick(dataset, case="wrong_iban")
    pipeline = Pipeline(dataset, session_factory, [clean, needs_review])

    class Dispatch:
        async def dispatch(self, document_id: uuid.UUID) -> None:
            await pipeline.run(document_id)

    app.dependency_overrides[get_storage] = lambda: pipeline.services.storage
    app.dependency_overrides[get_dispatcher] = lambda: Dispatch()
    async with session_factory() as setup:
        await upsert_purchase_orders(setup, pipeline.orders)
        await setup.commit()
    _as(client, "finance_clerk")
    assert "Documenten uploaden" in (await client.get("/upload")).text

    files = [
        ("files", (truth.filename, content, "application/pdf"))
        for truth, content in pipeline.documents
    ]
    files.append(("files", ("brief.docx", b"PK", "application/msword")))
    result = await client.post("/upload", files=files)
    assert result.text.count("Het document wordt verwerkt") == 2
    assert "Alleen pdf-bestanden worden geaccepteerd" in result.text

    queue = await client.get("/queue/rows")
    assert needs_review.filename in queue.text
    assert clean.filename not in queue.text  # auto-approved

    review_id = (
        await session.execute(select(Document.id).where(Document.filename == needs_review.filename))
    ).scalar_one()
    form = {name: "" for name in FIELD_KINDS}
    async with session_factory() as lookup:
        case = await review.load_case(lookup, review_id)
        assert case.invoice is not None
        form = {name: case.invoice.fields[name].value or "" for name in FIELD_KINDS}
    form["iban"] = dataset.plans[needs_review.doc_id].supplier.iban
    await client.post(f"/review/{review_id}/approve", data=form)

    _as(client, "team_lead")
    dashboard = await client.get("/dashboard")
    assert dashboard.status_code == 200
    # One of two invoices was handled without a person, and the other was corrected.
    assert '<div class="value" id="auto-share">50%</div>' in dashboard.text
    assert '<div class="value" id="corrected-share">100%</div>' in dashboard.text
    assert "1 van 2 facturen" in dashboard.text
    assert re.search(r"<td>\d{4}-\d{2}-\d{2}</td><td>2</td>", dashboard.text)
    assert "Automatisch goedgekeurd</td><td>1</td>" in dashboard.text
