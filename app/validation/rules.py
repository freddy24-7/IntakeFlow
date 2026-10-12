"""Deterministic validation (PRD F5). No model is involved in any of this.

Each check has a name. `validate` returns the names of the checks that failed,
and an empty list means the invoice passed. Auto-approval requires an empty
list (rule 3), whatever the model's score.
"""

import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from app.agents.schema import ExtractedInvoice
from app.validation.iban import is_valid_iban

ROUNDING = Decimal("0.01")
MAX_AGE = timedelta(days=5 * 365)
REQUIRED_FIELDS = (
    "supplier_name",
    "supplier_vat_number",
    "iban",
    "invoice_number",
    "invoice_date",
    "due_date",
    "currency",
    "subtotal",
    "vat",
    "total",
)
_NL_VAT = re.compile(r"^NL\d{9}B\d{2}$")
_EU_VAT = re.compile(r"^[A-Z]{2}[A-Z0-9]{2,12}$")


@dataclass(frozen=True)
class PurchaseOrderInfo:
    supplier_name: str
    supplier_vat_number: str
    amount: Decimal


@dataclass(frozen=True)
class ValidationContext:
    today: date
    # The purchase order the invoice refers to, or None when there is no such order.
    purchase_order: PurchaseOrderInfo | None
    # An earlier document has the same supplier and invoice number.
    is_duplicate: bool
    # Share of the order amount the invoice total may differ by.
    po_tolerance: Decimal


def _amount(invoice: ExtractedInvoice, name: str) -> Decimal | None:
    value = invoice.fields[name].value
    return None if value is None else Decimal(value)


def _date(invoice: ExtractedInvoice, name: str) -> date | None:
    value = invoice.fields[name].value
    return None if value is None else date.fromisoformat(value)


def same_company(first: str, second: str) -> bool:
    def key(name: str) -> str:
        return re.sub(r"[^a-z0-9]", "", name.casefold())

    return key(first) == key(second)


def is_valid_vat_number(number: str) -> bool:
    """Format only (PRD F5). Dutch numbers are NL, nine digits, B, two digits."""
    if number.startswith("NL"):
        return bool(_NL_VAT.match(number))
    return bool(_EU_VAT.match(number))


def _totals_add_up(invoice: ExtractedInvoice) -> bool:
    subtotal, vat, total = (_amount(invoice, name) for name in ("subtotal", "vat", "total"))
    if subtotal is None or vat is None or total is None or not invoice.line_items:
        return False
    line_totals = [line.line_total for line in invoice.line_items]
    if any(line_total is None for line_total in line_totals):
        return False
    lines = sum((Decimal(value) for value in line_totals if value is not None), Decimal(0))
    return abs(lines - subtotal) <= ROUNDING and abs(subtotal + vat - total) <= ROUNDING


def validate(invoice: ExtractedInvoice, context: ValidationContext) -> list[str]:
    failures = [f"missing_{name}" for name in REQUIRED_FIELDS if invoice.fields[name].value is None]

    # Totals equal the sum of the lines plus VAT, within rounding.
    if not _totals_add_up(invoice):
        failures.append("totals_mismatch")

    invoice_date, due_date = _date(invoice, "invoice_date"), _date(invoice, "due_date")
    if invoice_date is not None:
        if invoice_date > context.today or invoice_date < context.today - MAX_AGE:
            failures.append("invoice_date_implausible")
        if due_date is not None and due_date < invoice_date:
            failures.append("due_date_before_invoice_date")

    vat_number = invoice.fields["supplier_vat_number"].value
    if vat_number is not None and not is_valid_vat_number(vat_number):
        failures.append("vat_number_format")

    iban = invoice.fields["iban"].value
    if iban is not None and not is_valid_iban(iban):
        failures.append("iban_checksum")

    failures += _purchase_order_failures(invoice, context)

    if context.is_duplicate:
        failures.append("duplicate_invoice")

    # A flagged field (the two sources disagree, or the code could not read the
    # value back) always needs a person. Left to the score alone, one flagged
    # field is averaged away by ten confident ones.
    failures += [f"flagged_{name}" for name, field in invoice.fields.items() if field.flags]
    return failures


def _purchase_order_failures(invoice: ExtractedInvoice, context: ValidationContext) -> list[str]:
    if invoice.fields["purchase_order_reference"].value is None:
        return ["po_missing"]
    order = context.purchase_order
    if order is None:
        return ["po_not_found"]

    failures = []
    # Supplier matches on name or on VAT number. Either one is enough, so a
    # misprinted VAT number is reported by its own check and not twice.
    name = invoice.fields["supplier_name"].value
    vat_number = invoice.fields["supplier_vat_number"].value
    name_matches = name is not None and same_company(name, order.supplier_name)
    if not name_matches and vat_number != order.supplier_vat_number:
        failures.append("po_supplier_mismatch")

    total = _amount(invoice, "total")
    if total is not None and abs(total - order.amount) > abs(order.amount) * context.po_tolerance:
        failures.append("po_amount_out_of_tolerance")
    return failures
