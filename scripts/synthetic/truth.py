"""Ground-truth labels written next to every synthetic document.

`invoice` holds what is printed on the page, including deliberate errors, because
that is what extraction is measured against. `expected_failures` names the
validation checks that should catch the document, which is what routing is
measured against. A document with no expected failures is safe to auto-approve.
"""

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

DocumentType = Literal["invoice", "credit_note", "contract", "other"]

# Hard cases that change the content, mapped to the validation failure each should cause.
CONTENT_CASES: dict[str, str] = {
    "missing_po": "po_missing",
    "unknown_po": "po_not_found",
    "totals_mismatch": "totals_mismatch",
    "wrong_iban": "iban_checksum",
    "invalid_vat_number": "vat_number_format",
    "po_supplier_mismatch": "po_supplier_mismatch",
    "po_amount_mismatch": "po_amount_out_of_tolerance",
    "due_before_invoice": "due_date_before_invoice_date",
    "duplicate": "duplicate_invoice",
}
# Hard cases that only change how the page looks. Validation should still pass.
VISUAL_CASES = ("scanned", "scanned_skewed", "stamp")


class LineItem(BaseModel):
    description: str
    quantity: Decimal
    unit_price: Decimal
    vat_rate: Decimal
    line_total: Decimal


class InvoiceFields(BaseModel):
    supplier_name: str
    supplier_vat_number: str
    iban: str  # without spaces, also when printed in groups of four
    invoice_number: str
    invoice_date: date
    due_date: date
    currency: str
    line_items: list[LineItem]
    subtotal: Decimal
    vat: Decimal
    total: Decimal
    purchase_order_reference: str | None


class Clause(BaseModel):
    number: int
    heading: str
    topic: str
    page: int  # page on which the clause starts, 1-based
    text: str


class ContractTruth(BaseModel):
    contract_number: str
    title: str
    supplier_name: str
    # Facts stated in the clauses, as printed. A missing key means the contract
    # has no clause on that topic, so a question about it must be declined.
    facts: dict[str, str]
    clauses: list[Clause]


class DocumentTruth(BaseModel):
    doc_id: str
    filename: str
    doc_type: DocumentType
    language: Literal["nl", "en"]
    layout: str
    scanned: bool = False
    skew_degrees: float | None = None
    hard_cases: list[str] = []
    expected_failures: list[str] = []
    duplicate_of: str | None = None
    other_kind: str | None = None
    invoice: InvoiceFields | None = None
    contract: ContractTruth | None = None


class PurchaseOrderTruth(BaseModel):
    po_number: str
    supplier_name: str
    supplier_vat_number: str
    amount: Decimal
    currency: str
