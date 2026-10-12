"""The main path in a real browser: upload, queue, review with a correction, dashboard."""

import re
from pathlib import Path

from playwright.sync_api import Page, expect
from synthetic.build import Dataset
from synthetic.truth import DocumentTruth


def _digital(dataset: Dataset, hard_cases: list[str]) -> DocumentTruth:
    return next(
        doc
        for doc in dataset.documents
        if doc.doc_type == "invoice" and doc.hard_cases == hard_cases and not doc.scanned
    )


def test_upload_review_correct_approve_and_dashboard(
    page: Page, base_url: str, dataset: Dataset, pdf_folder: Path
) -> None:
    clean = _digital(dataset, [])
    wrong_iban = _digital(dataset, ["wrong_iban"])
    right_iban = dataset.plans[wrong_iban.doc_id].supplier.iban

    # Pick the clerk role and upload two invoices and a file that is not a PDF.
    page.goto(base_url)
    page.get_by_role("button", name="Financieel medewerker").click()
    expect(page.get_by_role("heading", name="Te beoordelen")).to_be_visible()
    page.get_by_role("link", name="Uploaden").click()
    not_a_pdf = pdf_folder / "brief.txt"
    not_a_pdf.write_text("geen pdf")
    page.set_input_files(
        "input[name=files]",
        [pdf_folder / clean.filename, pdf_folder / wrong_iban.filename, not_a_pdf],
    )
    page.get_by_role("button", name="Uploaden").click()
    expect(page.locator("#results")).to_contain_text("Alleen pdf-bestanden worden geaccepteerd")
    expect(page.locator("#results")).to_contain_text("Het document wordt verwerkt")

    # The queue refreshes by itself. Only the invoice with the wrong IBAN appears.
    # A second upload adds to the list. It does not replace the first result.
    page.set_input_files("input[name=files]", [not_a_pdf])
    page.get_by_role("button", name="Uploaden").click()
    expect(page.locator("#results .upload-result")).to_have_count(2)
    expect(page.locator("#results")).to_contain_text(clean.filename)

    page.get_by_role("link", name="Naar de beoordelingslijst").click()
    row = page.locator("tr", has_text=wrong_iban.filename)
    expect(row).to_contain_text("IBAN is ongeldig (controlegetal)", timeout=15_000)
    expect(page.locator("#queue")).not_to_contain_text(clean.filename)

    # Review: the document is shown next to the fields, and the failed check is named.
    row.get_by_role("link", name="Beoordelen").click()
    preview = page.locator("#pages img")
    expect(preview).to_have_count(1)
    expect(preview).to_have_js_property("complete", True)
    assert preview.evaluate("image => image.naturalWidth") > 500  # the page really rendered
    expect(page.locator("#reasons")).to_contain_text("IBAN is ongeldig")
    assert wrong_iban.invoice is not None
    expect(page.locator("#invoice_number")).to_have_value(wrong_iban.invoice.invoice_number)

    # Check without saving, correct the IBAN, check again, approve.
    page.get_by_role("button", name="Controleren").click()
    expect(page.locator("#check-result")).to_contain_text("U kunt toch goedkeuren")
    page.locator("#iban").fill(right_iban)
    page.get_by_role("button", name="Controleren").click()
    expect(page.locator("#check-result")).to_contain_text("slagen alle controles")
    page.get_by_role("button", name="Goedkeuren en boeken").click()
    expect(page.locator(".notice")).to_contain_text("goedgekeurd en geboekt")
    expect(page.locator("#queue-empty")).to_be_visible()

    # The team lead sees one invoice handled automatically and one corrected by a person.
    page.get_by_role("link", name="Andere rol").click()
    page.get_by_role("button", name="Teamleider").click()
    expect(page.locator("#auto-share")).to_have_text("50%")
    expect(page.locator("#corrected-share")).to_have_text("100%")
    expect(page.locator("#by-status")).to_contain_text(re.compile("Automatisch goedgekeurd"))
