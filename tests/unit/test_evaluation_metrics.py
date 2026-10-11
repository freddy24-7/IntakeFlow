from datetime import date
from decimal import Decimal

from evaluation import metrics
from evaluation.oracle import _llm_invoice
from synthetic.truth import DocumentTruth, InvoiceFields, LineItem

from app.agents.extract import merge
from app.agents.schema import FIELD_KINDS, FLAG_DI_DISAGREES, ExtractedInvoice

INVOICE = InvoiceFields(
    supplier_name="Arens Software B.V.",
    supplier_vat_number="NL942755630B73",
    iban="NL18HAVN1028439863",
    invoice_number="F2026-0001",
    invoice_date=date(2026, 3, 20),
    due_date=date(2026, 4, 19),
    currency="EUR",
    line_items=[
        LineItem(
            description="Advies (uur)",
            quantity=Decimal("2.5"),
            unit_price=Decimal("100"),
            vat_rate=Decimal("21"),
            line_total=Decimal("250.00"),
        )
    ],
    subtotal=Decimal("250.00"),
    vat=Decimal("52.50"),
    total=Decimal("302.50"),
    purchase_order_reference=None,
)
TRUTH = DocumentTruth(
    doc_id="doc-0001",
    filename="doc-0001.pdf",
    doc_type="invoice",
    language="nl",
    layout="classic",
    invoice=INVOICE,
)


def _perfect() -> ExtractedInvoice:
    return merge(_llm_invoice(TRUTH), None)


def test_truth_is_put_in_canonical_form() -> None:
    fields = metrics.truth_fields(INVOICE)

    assert fields["invoice_date"] == "2026-03-20"
    assert fields["total"] == "302.50"
    assert fields["purchase_order_reference"] is None
    assert metrics.truth_lines(INVOICE) == [("2.5", "100.00", "21", "250.00")]


def test_perfect_extraction_scores_everything_right() -> None:
    score = metrics.score_document(TRUTH, _perfect())

    assert set(score.correct) == {*FIELD_KINDS, "line_items"}
    assert score.exact


def test_one_wrong_field_breaks_exact_match_only_for_that_field() -> None:
    extracted = _perfect()
    extracted.fields["total"].value = "302.05"

    score = metrics.score_document(TRUTH, extracted)

    assert not score.correct["total"]
    assert score.correct["subtotal"]
    assert not score.exact


def test_inventing_a_value_for_an_absent_field_is_wrong() -> None:
    extracted = _perfect()
    extracted.fields["purchase_order_reference"].value = "PO-2026-00001"

    assert not metrics.score_document(TRUTH, extracted).correct["purchase_order_reference"]


def test_line_items_must_match_in_number_and_values() -> None:
    missing = _perfect()
    missing.line_items = []
    changed = _perfect()
    changed.line_items[0].quantity = "25"

    assert not metrics.score_document(TRUTH, missing).correct["line_items"]
    assert not metrics.score_document(TRUTH, changed).correct["line_items"]


def test_missing_extraction_counts_as_all_wrong() -> None:
    score = metrics.score_document(TRUTH, None)

    assert not any(score.correct.values())
    assert len(score.correct) == 12


def test_rates_and_summaries() -> None:
    wrong = _perfect()
    wrong.fields["total"].value = "1.00"
    wrong.fields["total"].flags = [FLAG_DI_DISAGREES]
    wrong.fields["iban"].flags = [FLAG_DI_DISAGREES]  # flagged although right
    wrong.fields["vat"].value = "9.99"  # wrong and not flagged
    scores = [metrics.score_document(TRUTH, _perfect()), metrics.score_document(TRUTH, wrong)]

    accuracy = metrics.field_accuracy(scores)
    assert str(accuracy["total"]) == "50.0% (1/2)"
    assert str(accuracy["iban"]) == "100.0% (2/2)"
    assert str(metrics.exact_match(scores)) == "50.0% (1/2)"
    caught, precise = metrics.flag_quality(scores)
    assert (caught.hits, caught.total) == (1, 2)  # of two wrong fields, one was flagged
    assert (precise.hits, precise.total) == (1, 2)  # of two flagged fields, one was wrong
    assert str(metrics.Rate(0, 0)) == "n/a"
    assert metrics.Rate(0, 0).value is None


def test_percentiles() -> None:
    values = [float(n) for n in range(1, 101)]

    assert metrics.percentile(values, 95) == 95.0
    assert metrics.percentile([10.0], 95) == 10.0
    assert metrics.percentile([], 95) is None
    assert metrics.median_or_none([1.0, 3.0]) == 2.0
    assert metrics.median_or_none([]) is None
