"""Compares extractions with the ground truth. Pure functions, no database.

A field is right when its canonical form equals the canonical form of the
label (see app.agents.normalise). There is no partial credit: a supplier name
that differs by one character is wrong.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import median

from synthetic.truth import DocumentTruth, InvoiceFields

from app.agents import normalise
from app.agents.schema import FIELD_KINDS, ExtractedInvoice

LINE_ITEMS = "line_items"


def truth_fields(invoice: InvoiceFields) -> dict[str, str | None]:
    """The label in canonical form, through the same code the pipeline uses."""
    raw = {
        "supplier_name": invoice.supplier_name,
        "supplier_vat_number": invoice.supplier_vat_number,
        "iban": invoice.iban,
        "invoice_number": invoice.invoice_number,
        "invoice_date": invoice.invoice_date.isoformat(),
        "due_date": invoice.due_date.isoformat(),
        "currency": invoice.currency,
        "subtotal": str(invoice.subtotal),
        "vat": str(invoice.vat),
        "total": str(invoice.total),
        "purchase_order_reference": invoice.purchase_order_reference,
    }
    return {name: normalise.canonical(kind, raw[name]) for name, kind in FIELD_KINDS.items()}


def truth_lines(invoice: InvoiceFields) -> list[tuple[str | None, ...]]:
    return [
        (
            normalise.canonical_number(str(line.quantity)),
            normalise.canonical(normalise.AMOUNT, str(line.unit_price)),
            normalise.canonical_number(str(line.vat_rate)),
            normalise.canonical(normalise.AMOUNT, str(line.line_total)),
        )
        for line in invoice.line_items
    ]


@dataclass(frozen=True)
class DocumentScore:
    doc_id: str
    correct: dict[str, bool]  # the eleven fields plus "line_items"
    flagged: dict[str, bool]  # per field: did the pipeline flag it?

    @property
    def exact(self) -> bool:
        return all(self.correct.values())


def score_document(truth: DocumentTruth, extracted: ExtractedInvoice | None) -> DocumentScore:
    """Score one invoice or credit note. No extraction (for example because the
    document was classified as something else) counts as every field wrong."""
    assert truth.invoice is not None
    names = [*FIELD_KINDS, LINE_ITEMS]
    if extracted is None:
        return DocumentScore(truth.doc_id, dict.fromkeys(names, False), dict.fromkeys(names, False))

    expected = truth_fields(truth.invoice)
    correct = {name: extracted.fields[name].value == expected[name] for name in FIELD_KINDS}
    flagged = {name: bool(extracted.fields[name].flags) for name in FIELD_KINDS}
    # Line items: the numbers on every line, in order. Descriptions are not compared.
    lines = [
        (line.quantity, line.unit_price, line.vat_rate, line.line_total)
        for line in extracted.line_items
    ]
    correct[LINE_ITEMS] = lines == truth_lines(truth.invoice)
    flagged[LINE_ITEMS] = False
    return DocumentScore(truth.doc_id, correct, flagged)


@dataclass(frozen=True)
class Rate:
    hits: int
    total: int

    @property
    def value(self) -> float | None:
        return self.hits / self.total if self.total else None

    def __str__(self) -> str:
        if not self.total:
            return "n/a"
        return f"{100 * self.hits / self.total:.1f}% ({self.hits}/{self.total})"


def field_accuracy(scores: Sequence[DocumentScore]) -> dict[str, Rate]:
    names = [*FIELD_KINDS, LINE_ITEMS]
    return {name: Rate(sum(score.correct[name] for score in scores), len(scores)) for name in names}


def exact_match(scores: Sequence[DocumentScore]) -> Rate:
    return Rate(sum(score.exact for score in scores), len(scores))


def flag_quality(scores: Sequence[DocumentScore]) -> tuple[Rate, Rate]:
    """(share of wrong fields that were flagged, share of flagged fields that were wrong)."""
    cells = [(score.correct[name], score.flagged[name]) for score in scores for name in FIELD_KINDS]
    wrong = [flagged for correct, flagged in cells if not correct]
    flagged_cells = [correct for correct, flagged in cells if flagged]
    return (
        Rate(sum(wrong), len(wrong)),
        Rate(sum(not correct for correct in flagged_cells), len(flagged_cells)),
    )


def percentile(values: Sequence[float], percent: float) -> float | None:
    """Nearest-rank percentile."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(percent / 100 * len(ordered)))
    return ordered[rank - 1]


def median_or_none(values: Sequence[float]) -> float | None:
    return median(values) if values else None
