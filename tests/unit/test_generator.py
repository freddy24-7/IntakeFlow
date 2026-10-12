"""The synthetic set: same seed gives the same data, and every hard case is present and labelled."""

import json
from collections import Counter
from pathlib import Path

import pytest
from synthetic.build import CONTENT_SHARES, VISUAL_SHARES, Dataset, generate, plan_counts, totals
from synthetic.iban import is_valid_iban, with_check_digits
from synthetic.questions import accepted_values, make_questions
from synthetic.render import format_money, layout_contract
from synthetic.truth import CONTENT_CASES, DocumentTruth
from synthetic.write import render_document, write_dataset

from app.common.dutch import format_dutch_decimal
from app.reading.fakes import extract_text_layer

DOCUMENTS = 60
SEED = 42


@pytest.fixture(scope="module")
def dataset() -> Dataset:
    return generate(DOCUMENTS, SEED)


def _money(dataset: Dataset) -> list[DocumentTruth]:
    return [doc for doc in dataset.documents if doc.invoice is not None]


def _with_case(dataset: Dataset, case: str) -> list[DocumentTruth]:
    return [doc for doc in dataset.documents if case in doc.hard_cases]


def _text(dataset: Dataset, doc: DocumentTruth) -> str:
    pdf = render_document(doc, dataset.plans[doc.doc_id])
    return "\n".join(page.text for page in extract_text_layer(pdf))


def test_same_seed_gives_the_same_labels_and_the_same_pdf_bytes(dataset: Dataset) -> None:
    again = generate(DOCUMENTS, SEED)

    assert again.documents == dataset.documents
    assert again.purchase_orders == dataset.purchase_orders
    for doc in dataset.documents[:15]:
        first = render_document(doc, dataset.plans[doc.doc_id])
        assert render_document(doc, again.plans[doc.doc_id]) == first


def test_another_seed_gives_other_documents(dataset: Dataset) -> None:
    assert generate(DOCUMENTS, SEED + 1).documents != dataset.documents


def test_document_mix_matches_the_plan(dataset: Dataset) -> None:
    counts = plan_counts(DOCUMENTS)
    by_type = Counter(doc.doc_type for doc in dataset.documents)

    assert len(dataset.documents) == DOCUMENTS
    assert by_type["contract"] == counts.contracts
    assert by_type["other"] == counts.others
    assert by_type["credit_note"] >= counts.credit_notes
    assert len({doc.doc_id for doc in dataset.documents}) == DOCUMENTS
    assert {doc.language for doc in _money(dataset)} == {"nl", "en"}
    assert len({doc.layout for doc in _money(dataset)}) >= 3


def test_too_small_a_set_is_refused() -> None:
    with pytest.raises(ValueError, match="at least"):
        generate(10, SEED)


def test_every_hard_case_is_present_and_labelled(dataset: Dataset) -> None:
    for case in [*CONTENT_SHARES, *VISUAL_SHARES, "duplicate"]:
        assert _with_case(dataset, case), f"no document with hard case {case}"

    for doc in dataset.documents:
        expected = [CONTENT_CASES[case] for case in doc.hard_cases if case in CONTENT_CASES]
        assert doc.expected_failures == expected
        assert len(doc.expected_failures) <= 1


def test_amounts_add_up_except_where_labelled(dataset: Dataset) -> None:
    for doc in _money(dataset):
        assert doc.invoice is not None
        subtotal, vat, total = totals(doc.invoice.line_items)
        assert (doc.invoice.subtotal, doc.invoice.vat) == (subtotal, vat)
        if "totals_mismatch" in doc.hard_cases:
            assert doc.invoice.total != total
        else:
            assert doc.invoice.total == total


def test_ibans_and_vat_numbers_are_valid_except_where_labelled(dataset: Dataset) -> None:
    for doc in _money(dataset):
        assert doc.invoice is not None
        assert is_valid_iban(doc.invoice.iban) == ("wrong_iban" not in doc.hard_cases)
        well_formed = len(doc.invoice.supplier_vat_number) == 14
        assert well_formed == ("invalid_vat_number" not in doc.hard_cases)


def test_dates_are_in_order_except_where_labelled(dataset: Dataset) -> None:
    for doc in _money(dataset):
        assert doc.invoice is not None
        early = doc.invoice.due_date < doc.invoice.invoice_date
        assert early == ("due_before_invoice" in doc.hard_cases)


def test_purchase_orders_match_the_labels(dataset: Dataset) -> None:
    orders = {po.po_number: po for po in dataset.purchase_orders}
    for doc in _money(dataset):
        assert doc.invoice is not None
        reference = doc.invoice.purchase_order_reference
        cases = doc.hard_cases
        if "missing_po" in cases:
            assert reference is None
            continue
        assert reference is not None
        if "unknown_po" in cases:
            assert reference not in orders
            continue
        order = orders[reference]
        assert (order.supplier_name != doc.invoice.supplier_name) == (
            "po_supplier_mismatch" in cases
        )
        if "po_amount_mismatch" in cases:
            assert order.amount < doc.invoice.total * 9 / 10
        elif "totals_mismatch" not in cases:
            assert order.amount == doc.invoice.total


def test_a_duplicate_repeats_an_earlier_document(dataset: Dataset) -> None:
    by_id = {doc.doc_id: doc for doc in dataset.documents}
    numbers = Counter(
        (doc.invoice.supplier_name, doc.invoice.invoice_number)
        for doc in dataset.documents
        if doc.invoice
    )
    for doc in _with_case(dataset, "duplicate"):
        assert doc.duplicate_of is not None
        assert doc.duplicate_of < doc.doc_id
        assert by_id[doc.duplicate_of].invoice == doc.invoice
        assert by_id[doc.duplicate_of].expected_failures == []
    # Apart from the labelled duplicates, supplier and number are unique.
    assert sum(count - 1 for count in numbers.values()) == len(_with_case(dataset, "duplicate"))


def test_digital_invoice_prints_what_the_label_says(dataset: Dataset) -> None:
    dutch = next(
        doc for doc in _money(dataset) if doc.language == "nl" and not doc.scanned and doc.invoice
    )
    english = next(
        doc for doc in _money(dataset) if doc.language == "en" and not doc.scanned and doc.invoice
    )
    assert dutch.invoice is not None
    assert english.invoice is not None

    dutch_text = _text(dataset, dutch)
    assert dutch.invoice.invoice_number in dutch_text
    assert dutch.invoice.supplier_vat_number in dutch_text
    # Dutch layout: 1.234,56
    assert format_dutch_decimal(dutch.invoice.total) in dutch_text
    assert dutch.invoice.iban in dutch_text.replace(" ", "")

    english_text = _text(dataset, english)
    # English layout: 1,234.56
    assert f"{english.invoice.total:,.2f}" in english_text
    assert format_money(english.invoice.total, "en") in english_text


def test_missing_po_is_not_printed(dataset: Dataset) -> None:
    doc = next(d for d in _with_case(dataset, "missing_po") if not d.scanned)
    assert "PO-2026-" not in _text(dataset, doc)


def test_scanned_documents_have_no_text_layer(dataset: Dataset) -> None:
    scanned = _with_case(dataset, "scanned")[0]
    skewed = _with_case(dataset, "scanned_skewed")[0]

    assert scanned.scanned
    assert scanned.skew_degrees is None
    assert skewed.scanned
    assert skewed.skew_degrees is not None
    assert 1.5 <= abs(skewed.skew_degrees) <= 4.0
    assert _text(dataset, scanned).strip() == ""
    assert _text(dataset, skewed).strip() == ""


def test_contract_labels_match_the_pages(dataset: Dataset) -> None:
    contracts = [doc for doc in dataset.documents if doc.contract is not None]
    left_out_somewhere = False
    for doc in contracts:
        assert doc.contract is not None
        pdf = render_document(doc, dataset.plans[doc.doc_id])
        pages = extract_text_layer(pdf)
        assert len(pages) >= 2
        for clause in doc.contract.clauses:
            heading = f"Artikel {clause.number}. {clause.heading}"
            assert heading in pages[clause.page - 1].text
        _, clause_pages = layout_contract(doc.contract)
        assert {c.number: c.page for c in doc.contract.clauses} == clause_pages

        topics = {clause.topic for clause in doc.contract.clauses}
        assert "notice_period_months" in doc.contract.facts
        # A fact is only labelled when its clause is in the contract.
        assert ("liability_cap_eur" in doc.contract.facts) == ("liability" in topics)
        assert ("indexation_cap_percent" in doc.contract.facts) == ("price_indexation" in topics)
        left_out_somewhere |= len(topics) < 9
        notice = doc.contract.facts["notice_period_months"]
        assert f"opzegtermijn van {notice} maanden" in "\n".join(p.text for p in pages).replace(
            "\r\n", " "
        ).replace("\n", " ")
    assert left_out_somewhere, "no contract leaves a clause out, so nothing is unanswerable"


def test_other_documents_carry_no_invoice_label(dataset: Dataset) -> None:
    for doc in dataset.documents:
        if doc.doc_type == "other":
            assert doc.invoice is None
            assert doc.contract is None
            assert doc.other_kind is not None
            assert _text(dataset, doc).strip()


def test_iban_check_digits() -> None:
    iban = with_check_digits("NL", "DELT0123456789")
    assert is_valid_iban(iban)
    assert is_valid_iban(f"{iban[:4]} {iban[4:8]} {iban[8:]}")
    assert not is_valid_iban(iban[:-1] + ("0" if iban[-1] != "0" else "1"))
    assert not is_valid_iban("NL")


def test_written_files_round_trip(dataset: Dataset, tmp_path: Path) -> None:
    (tmp_path / "documents").mkdir()
    (tmp_path / "documents" / "doc-9999.pdf").write_bytes(b"stale")

    write_dataset(dataset, tmp_path)

    documents_dir = tmp_path / "documents"
    assert len(list(documents_dir.glob("*.pdf"))) == DOCUMENTS
    assert len(list(documents_dir.glob("*.json"))) == DOCUMENTS
    assert not (documents_dir / "doc-9999.pdf").exists()
    for doc in dataset.documents:
        stored = (documents_dir / f"{doc.doc_id}.json").read_text(encoding="utf-8")
        assert DocumentTruth.model_validate_json(stored) == doc
        assert (documents_dir / doc.filename).read_bytes().startswith(b"%PDF")

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["seed"] == SEED
    assert manifest["documents"] == DOCUMENTS
    orders = json.loads((tmp_path / "purchase_orders.json").read_text(encoding="utf-8"))
    assert len(orders) == len(dataset.purchase_orders)


@pytest.mark.parametrize(("folder", "seed"), [("synthetic", 42), ("synthetic-holdout", 43)])
def test_committed_ground_truth_is_what_the_generator_produces(folder: str, seed: int) -> None:
    """Labels in the repository come from the generator and are never edited by hand."""
    documents_dir = Path(__file__).resolve().parents[2] / "data" / folder / "documents"
    expected = generate(200, seed)

    stored = sorted(documents_dir.glob("doc-*.json"))
    assert len(stored) == len(expected.documents)
    for path, doc in zip(stored, expected.documents, strict=True):
        assert DocumentTruth.model_validate_json(path.read_text(encoding="utf-8")) == doc


def test_questions_are_labelled_from_the_contract_facts(dataset: Dataset) -> None:
    questions = make_questions(dataset.documents)
    by_id = {doc.doc_id: doc for doc in dataset.documents}

    assert len({question.question_id for question in questions}) == len(questions)
    assert {question.phrasing for question in questions} == {"near", "paraphrase", "english"}
    assert any(not q.answerable and q.doc_id for q in questions)  # a clause the contract lacks
    assert any(q.doc_id is None for q in questions)  # a subject no contract covers
    for question in questions:
        if not question.answerable:
            assert question.accepted == []
            assert question.clause_number is None
            continue
        assert question.doc_id is not None
        contract = by_id[question.doc_id].contract
        assert contract is not None
        clause = next(c for c in contract.clauses if c.number == question.clause_number)
        assert (clause.topic, clause.page) == (question.topic, question.page)
        assert contract.supplier_name in question.question
        # The labelled value is really in the clause the question points to.
        assert question.accepted[0] in clause.text


def test_accepted_forms_of_a_value() -> None:
    assert accepted_values("liability_cap_eur", "250.000,00") == [
        "250.000,00",
        "250.000",
        "250000",
        "250,000",
    ]
    assert accepted_values("indexation_cap_percent", "2,5") == ["2,5", "2.5"]
    assert accepted_values("court", "Rotterdam") == ["Rotterdam"]
