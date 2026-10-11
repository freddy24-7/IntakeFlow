"""Draws the synthetic documents as PDFs with reportlab.

`invariant=1` leaves timestamps out of the files, so the same seed gives the
same bytes.
"""

import io
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen.canvas import Canvas

from app.common.dutch import format_dutch_date, format_dutch_date_long, format_dutch_decimal
from synthetic.catalog import BUYER_LINES, BUYER_NAME, LABELS, LAYOUTS, Supplier
from synthetic.truth import ContractTruth, DocumentTruth, InvoiceFields

PAGE_WIDTH, PAGE_HEIGHT = float(A4[0]), float(A4[1])
MARGIN = 50.0
LEFT, RIGHT, TOP = MARGIN, PAGE_WIDTH - MARGIN, PAGE_HEIGHT - MARGIN
CENT = Decimal("0.01")
ENGLISH_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def format_money(value: Decimal, language: str) -> str:
    if language == "nl":
        return f"€ {format_dutch_decimal(value)}"
    return f"€{value:,.2f}"


def format_quantity(value: Decimal, language: str) -> str:
    if value == value.to_integral_value():
        return str(int(value))
    return f"{value:.1f}".replace(".", ",") if language == "nl" else f"{value:.1f}"


def format_date(value: date, language: str, style: str) -> str:
    if language == "nl":
        return format_dutch_date_long(value) if style == "long" else format_dutch_date(value)
    if style == "iso":
        return value.isoformat()
    return f"{value.day} {ENGLISH_MONTHS[value.month - 1]} {value.year}"


def format_iban(iban: str, grouped: bool) -> str:
    if not grouped:
        return iban
    return " ".join(iban[index : index + 4] for index in range(0, len(iban), 4))


def vat_by_rate(invoice: InvoiceFields) -> dict[Decimal, Decimal]:
    """VAT amount per rate, rounded per rate. The invoice's VAT is the sum of these."""
    bases: dict[Decimal, Decimal] = defaultdict(Decimal)
    for line in invoice.line_items:
        bases[line.vat_rate] += line.line_total
    return {
        rate: (base * rate / 100).quantize(CENT, ROUND_HALF_UP)
        for rate, base in sorted(bases.items(), reverse=True)
    }


def _text(
    canvas: Any, x: float, y: float, text: str, font: str, size: float, align: str = "left"
) -> None:
    canvas.setFont(font, size)
    if align == "right":
        canvas.drawRightString(x, y, text)
    else:
        canvas.drawString(x, y, text)


def _finish(canvas: Any, buffer: io.BytesIO) -> bytes:
    canvas.save()
    return buffer.getvalue()


def render_invoice(doc: DocumentTruth, supplier: Supplier, stamp_text: str | None = None) -> bytes:
    """One-page invoice or credit note in the supplier's own layout, labels and formats."""
    invoice = doc.invoice
    assert invoice is not None
    layout = LAYOUTS[supplier.layout]
    labels = LABELS[supplier.language][supplier.label_variant]
    language = supplier.language
    iban = format_iban(invoice.iban, supplier.iban_grouped)

    def money(value: Decimal) -> str:
        return format_money(value, language)

    def day(value: date) -> str:
        return format_date(value, language, supplier.date_style)

    buffer = io.BytesIO()
    canvas = Canvas(buffer, pagesize=A4, invariant=1)
    supplier_x, supplier_align = (LEFT, "left") if layout.supplier_left else (RIGHT, "right")
    other_x, other_align = (RIGHT, "right") if layout.supplier_left else (LEFT, "left")

    # Title, on the side opposite the supplier
    title = labels.credit_title if doc.doc_type == "credit_note" else labels.invoice_title
    if layout.band:
        canvas.setFillColorRGB(*layout.accent)
        canvas.rect(0, PAGE_HEIGHT - 28, PAGE_WIDTH, 28, fill=1, stroke=0)
    canvas.setFillColorRGB(*layout.accent)
    _text(canvas, other_x, TOP - 12, title, layout.bold_font, 20, other_align)
    canvas.setFillColorRGB(0, 0, 0)

    # Supplier block
    supplier_lines = [supplier.street, supplier.postcode_city, f"{labels.chamber} {supplier.kvk}"]
    if not layout.details_in_footer:
        supplier_lines.append(f"{labels.vat_number}: {invoice.supplier_vat_number}")
        supplier_lines.append(f"{labels.iban}: {iban}")
    _text(canvas, supplier_x, TOP - 10, invoice.supplier_name, layout.bold_font, 12, supplier_align)
    for index, line in enumerate(supplier_lines, start=1):
        _text(canvas, supplier_x, TOP - 10 - 14 * index, line, layout.font, 9.5, supplier_align)

    # Buyer block and invoice details
    block_top = TOP - 125
    _text(canvas, other_x, block_top, labels.bill_to, layout.font, 8, other_align)
    for index, line in enumerate(BUYER_LINES, start=1):
        font = layout.bold_font if index == 1 else layout.font
        _text(canvas, other_x, block_top - 14 * index, line, font, 10, other_align)

    details = [
        (labels.number, invoice.invoice_number),
        (labels.date, day(invoice.invoice_date)),
        (labels.due, day(invoice.due_date)),
    ]
    if invoice.purchase_order_reference:
        details.append((labels.po, invoice.purchase_order_reference))
    for index, (label, value) in enumerate(details):
        y = block_top - 14 * index
        _text(canvas, supplier_x, y, f"{label}: {value}", layout.font, 10, supplier_align)

    # Line items
    columns = (
        (labels.description, LEFT + 4, "left"),
        (labels.quantity, 330.0, "right"),
        (labels.unit_price, 405.0, "right"),
        (labels.vat_rate, 450.0, "right"),
        (labels.amount, RIGHT - 4, "right"),
    )
    y = TOP - 235
    if layout.table_fill:
        canvas.setFillColorRGB(0.9, 0.9, 0.9)
        canvas.rect(LEFT, y - 5, RIGHT - LEFT, 17, fill=1, stroke=0)
        canvas.setFillColorRGB(0, 0, 0)
    else:
        canvas.line(LEFT, y - 5, RIGHT, y - 5)
    for label, x, align in columns:
        _text(canvas, x, y, label, layout.bold_font, 9.5, align)
    for line_item in invoice.line_items:
        y -= 18
        cells = (
            line_item.description,
            format_quantity(line_item.quantity, language),
            money(line_item.unit_price),
            f"{int(line_item.vat_rate)}%",
            money(line_item.line_total),
        )
        for cell, (_, x, align) in zip(cells, columns, strict=True):
            _text(canvas, x, y, cell, layout.font, 9.5, align)
    canvas.line(LEFT, y - 8, RIGHT, y - 8)

    # Totals
    rates = {rate: amount for rate, amount in vat_by_rate(invoice).items() if rate > 0}
    totals = [(labels.subtotal, invoice.subtotal)]
    if len(rates) > 1:
        totals.extend((f"{labels.vat} {int(rate)}%", amount) for rate, amount in rates.items())
    else:
        totals.append((labels.vat, invoice.vat))
    y -= 12
    for total_label, amount in totals:
        y -= 16
        _text(canvas, 450.0, y, total_label, layout.font, 10, "right")
        _text(canvas, RIGHT - 4, y, money(amount), layout.font, 10, "right")
    y -= 20
    _text(canvas, 450.0, y, labels.total, layout.bold_font, 11.5, "right")
    _text(canvas, RIGHT - 4, y, money(invoice.total), layout.bold_font, 11.5, "right")

    if stamp_text:
        _draw_stamp(canvas, stamp_text, y)

    # Footer
    payment = labels.payment.format(
        days=supplier.payment_term_days, iban=iban, number=invoice.invoice_number
    )
    footer = simpleSplit(payment, layout.font, 9, RIGHT - LEFT)
    if layout.details_in_footer:
        footer.append(
            f"{invoice.supplier_name} | {labels.vat_number} {invoice.supplier_vat_number}"
            f" | {labels.iban} {iban}"
        )
    for index, line in enumerate(footer):
        _text(canvas, LEFT, 92 - 12 * index, line, layout.font, 9)

    canvas.showPage()
    return _finish(canvas, buffer)


def _draw_stamp(canvas: Any, text: str, y: float) -> None:
    """A red, rotated rubber stamp that partly covers the totals."""
    canvas.saveState()
    canvas.translate(RIGHT - 150, y + 12)
    canvas.rotate(14)
    canvas.setStrokeColorRGB(0.8, 0.1, 0.1)
    canvas.setFillColorRGB(0.8, 0.1, 0.1)
    canvas.setStrokeAlpha(0.7)
    canvas.setFillAlpha(0.7)
    canvas.setLineWidth(2.5)
    canvas.roundRect(0, 0, 150, 38, 5, fill=0, stroke=1)
    canvas.setFont("Helvetica-Bold", 20)
    canvas.drawCentredString(75, 11, text)
    canvas.restoreState()


@dataclass(frozen=True)
class PlacedLine:
    text: str
    font: str
    size: float
    y: float


def layout_contract(contract: ContractTruth) -> tuple[list[list[PlacedLine]], dict[int, int]]:
    """Paginate a contract. Returns the lines per page and the start page of each clause.

    The generator uses the page numbers as ground truth, and the renderer draws
    exactly these lines, so the label and the PDF cannot drift apart.
    """
    width = RIGHT - LEFT - 20
    bottom = MARGIN + 30
    pages: list[list[PlacedLine]] = [[]]
    y = TOP

    def emit(text: str, font: str, size: float, leading: float) -> None:
        nonlocal y
        for line in simpleSplit(text, font, size, width):
            if y < bottom:
                pages.append([])
                y = TOP
            pages[-1].append(PlacedLine(line, font, size, y))
            y -= leading

    emit(contract.title, "Times-Bold", 14, 20)
    emit(f"Contractnummer {contract.contract_number}", "Times-Roman", 10.5, 24)
    emit("Partijen", "Times-Bold", 12, 18)
    emit(
        f"1. {BUYER_NAME}, gevestigd te Rotterdam, hierna te noemen 'Opdrachtgever';",
        "Times-Roman",
        11,
        16,
    )
    emit(f"2. {contract.supplier_name}, hierna te noemen 'Leverancier';", "Times-Roman", 11, 16)
    emit("komen het volgende overeen.", "Times-Roman", 11, 16)

    clause_pages = {}
    for clause in contract.clauses:
        y -= 18
        if y < bottom + 70:  # keep a heading together with the start of its text
            pages.append([])
            y = TOP
        clause_pages[clause.number] = len(pages)
        emit(f"Artikel {clause.number}. {clause.heading}", "Times-Bold", 12, 18)
        for paragraph_number, paragraph in enumerate(clause.text.split("\n"), start=1):
            emit(f"{clause.number}.{paragraph_number}  {paragraph}", "Times-Roman", 11, 15.5)
            y -= 5

    y -= 30
    emit("Aldus overeengekomen en in tweevoud ondertekend te Rotterdam.", "Times-Roman", 11, 44)
    emit(
        f"{BUYER_NAME}                                  {contract.supplier_name}",
        "Times-Roman",
        11,
        16,
    )
    return pages, clause_pages


def render_contract(contract: ContractTruth) -> bytes:
    pages, _ = layout_contract(contract)
    buffer = io.BytesIO()
    canvas = Canvas(buffer, pagesize=A4, invariant=1)
    for number, lines in enumerate(pages, start=1):
        for line in lines:
            _text(canvas, LEFT + 10, line.y, line.text, line.font, line.size)
        footer = f"{contract.contract_number} - pagina {number} van {len(pages)}"
        _text(canvas, RIGHT, MARGIN - 10, footer, "Times-Roman", 9, "right")
        canvas.showPage()
    return _finish(canvas, buffer)


def render_letter(supplier: Supplier, heading: str, paragraphs: list[str]) -> bytes:
    """A plain one-page letter, for documents that are neither invoice nor contract."""
    buffer = io.BytesIO()
    canvas = Canvas(buffer, pagesize=A4, invariant=1)
    _text(canvas, LEFT, TOP - 10, supplier.name, "Helvetica-Bold", 12)
    _text(canvas, LEFT, TOP - 24, supplier.street, "Helvetica", 9.5)
    _text(canvas, LEFT, TOP - 38, supplier.postcode_city, "Helvetica", 9.5)
    for index, line in enumerate(BUYER_LINES):
        _text(canvas, LEFT, TOP - 100 - 14 * index, line, "Helvetica", 10)
    _text(canvas, LEFT, TOP - 200, heading, "Helvetica-Bold", 13)
    y = TOP - 230
    for paragraph in paragraphs:
        for line in simpleSplit(paragraph, "Helvetica", 10.5, RIGHT - LEFT):
            _text(canvas, LEFT, y, line, "Helvetica", 10.5)
            y -= 15
        y -= 9
    canvas.showPage()
    return _finish(canvas, buffer)
