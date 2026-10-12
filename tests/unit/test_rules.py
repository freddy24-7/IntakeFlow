"""PRD F5: every validation check, on its own."""

from datetime import date
from decimal import Decimal

import pytest

from app.agents.schema import FIELD_KINDS, ExtractedInvoice, ExtractedLine, FieldValue
from app.validation.iban import is_valid_iban
from app.validation.rules import (
    PurchaseOrderInfo,
    ValidationContext,
    is_valid_vat_number,
    same_company,
    validate,
)

TODAY = date(2026, 10, 12)
ORDER = PurchaseOrderInfo("Arens Software B.V.", "NL942755630B73", Decimal("302.50"))
VALUES = {
    "supplier_name": "Arens Software B.V.",
    "supplier_vat_number": "NL942755630B73",
    "iban": "NL91ABNA0417164300",
    "invoice_number": "F2026-0001",
    "invoice_date": "2026-03-20",
    "due_date": "2026-04-19",
    "currency": "EUR",
    "subtotal": "250.00",
    "vat": "52.50",
    "total": "302.50",
    "purchase_order_reference": "PO-2026-00001",
}


def _invoice(**changes: str | None) -> ExtractedInvoice:
    values = {**VALUES, **changes}
    assert set(values) == set(FIELD_KINDS)
    lines = [
        ExtractedLine(description="a", quantity="2", unit_price="100.00", line_total="200.00"),
        ExtractedLine(description="b", quantity="1", unit_price="50.00", line_total="50.00"),
    ]
    fields = {name: FieldValue(value=value) for name, value in values.items()}
    return ExtractedInvoice(fields=fields, line_items=lines)


def _context(order: PurchaseOrderInfo | None = ORDER, duplicate: bool = False) -> ValidationContext:
    return ValidationContext(
        today=TODAY, purchase_order=order, is_duplicate=duplicate, po_tolerance=Decimal("0.01")
    )


def test_a_correct_invoice_passes_every_check() -> None:
    assert validate(_invoice(), _context()) == []


@pytest.mark.parametrize(
    ("changes", "failure"),
    [
        ({"total": "312.50"}, "totals_mismatch"),
        ({"subtotal": "240.00", "total": "292.50"}, "totals_mismatch"),  # lines do not add up
        ({"due_date": "2026-03-10"}, "due_date_before_invoice_date"),
        ({"invoice_date": "2026-11-01", "due_date": "2026-12-01"}, "invoice_date_implausible"),
        ({"invoice_date": "2019-01-01"}, "invoice_date_implausible"),
        ({"supplier_vat_number": "NL94275563B73"}, "vat_number_format"),
        ({"iban": "NL91ABNA0417164301"}, "iban_checksum"),
        ({"iban": "NL91ABNA041716430"}, "iban_checksum"),  # too short
        ({"purchase_order_reference": None}, "po_missing"),
        ({"invoice_number": None}, "missing_invoice_number"),
    ],
)
def test_each_problem_fails_its_own_check(changes: dict[str, str | None], failure: str) -> None:
    assert failure in validate(_invoice(**changes), _context())


def test_a_wrong_total_fails_only_the_totals_check_when_within_tolerance() -> None:
    assert validate(_invoice(total="303.50"), _context()) == ["totals_mismatch"]


def test_one_cent_of_rounding_is_allowed() -> None:
    assert validate(_invoice(vat="52.51", total="302.51"), _context()) == []


def test_missing_line_amounts_fail_the_totals_check() -> None:
    invoice = _invoice()
    invoice.line_items[0].line_total = None
    no_lines = _invoice()
    no_lines.line_items = []

    assert validate(invoice, _context()) == ["totals_mismatch"]
    assert validate(no_lines, _context()) == ["totals_mismatch"]


def test_purchase_order_checks() -> None:
    other_supplier = PurchaseOrderInfo("Bandenservice Willems", "NL111111111B01", Decimal("302.50"))
    lower_amount = PurchaseOrderInfo("Arens Software B.V.", "NL942755630B73", Decimal("250.00"))
    within_one_percent = PurchaseOrderInfo(
        "Arens Software B.V.", "NL942755630B73", Decimal("300.00")
    )

    assert validate(_invoice(), _context(order=None)) == ["po_not_found"]
    assert validate(_invoice(), _context(other_supplier)) == ["po_supplier_mismatch"]
    assert validate(_invoice(), _context(lower_amount)) == ["po_amount_out_of_tolerance"]
    assert validate(_invoice(), _context(within_one_percent)) == []


def test_supplier_matches_on_name_or_vat_number() -> None:
    """A misprinted VAT number is reported once, by its own check."""
    spelled_differently = _invoice(supplier_name="ARENS SOFTWARE BV")
    wrong_vat = _invoice(supplier_vat_number="NL94275563B73")
    other_name_same_vat = _invoice(supplier_name="Arens Holding")

    assert validate(spelled_differently, _context()) == []
    assert validate(wrong_vat, _context()) == ["vat_number_format"]
    assert validate(other_name_same_vat, _context()) == []
    assert same_company("Driessen&KronenbergAdviesV.O.F.", "Driessen & Kronenberg Advies V.O.F.")


def test_duplicate_is_reported() -> None:
    assert validate(_invoice(), _context(duplicate=True)) == ["duplicate_invoice"]


def test_several_problems_are_all_reported() -> None:
    failures = validate(
        _invoice(iban="NL00XXXX0000000000", due_date="2026-01-01", total="1.00"),
        _context(order=None),
    )

    assert failures == [
        "totals_mismatch",
        "due_date_before_invoice_date",
        "iban_checksum",
        "po_not_found",
    ]


def test_iban_and_vat_number_helpers() -> None:
    assert is_valid_iban("NL91ABNA0417164300")
    assert is_valid_iban("BE68539007547034")
    assert not is_valid_iban("NL91 ABNA 0417 1643 00")  # canonical form has no spaces
    assert not is_valid_iban("XX")
    assert is_valid_vat_number("NL942755630B73")
    assert not is_valid_vat_number("NL942755630B7")
    assert is_valid_vat_number("BE0123456789")
    assert not is_valid_vat_number("12345")
