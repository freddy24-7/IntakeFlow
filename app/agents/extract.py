"""Invoice extraction (PRD F4), in three variants for the baseline comparison.

- `di_only`: the fields Document Intelligence's prebuilt invoice model returned.
- `llm_only`: the model reads the page text.
- `combined`: the model reads the page text with Document Intelligence's fields
  as a second opinion, and every field where the two disagree is flagged.
"""

import re

from app.agents import normalise
from app.agents.prompts import Prompt
from app.agents.schema import (
    FIELD_KINDS,
    FLAG_DI_DISAGREES,
    FLAG_NORMALISATION_MISMATCH,
    FLAG_UNPARSEABLE,
    ExtractedInvoice,
    ExtractedLine,
    FieldValue,
    LlmField,
    LlmInvoice,
)
from app.inference.interfaces import ChatModel, ModelUsage
from app.reading.interfaces import ReadField, ReadResult

VARIANT_COMBINED, VARIANT_LLM_ONLY, VARIANT_DI_ONLY = "combined", "llm_only", "di_only"
VARIANTS = (VARIANT_COMBINED, VARIANT_LLM_ONLY, VARIANT_DI_ONLY)

# Our field -> the name app.reading gives the matching Document Intelligence field.
DI_FIELD_NAMES = {
    "supplier_name": "VendorName",
    "supplier_vat_number": "VendorTaxId",
    "iban": "PaymentDetails[0].IBAN",
    "invoice_number": "InvoiceId",
    "invoice_date": "InvoiceDate",
    "due_date": "DueDate",
    "currency": "CurrencyCode",
    "subtotal": "SubTotal",
    "vat": "TotalTax",
    "total": "InvoiceTotal",
    "purchase_order_reference": "PurchaseOrder",
}
_ITEM_FIELD = re.compile(r"^Items\[(\d+)\]\.(\w+)$")
_CHECKED_AGAINST_SOURCE = (normalise.AMOUNT, normalise.DATE)


def di_fields_to_invoice(fields: list[ReadField]) -> ExtractedInvoice:
    """The `di_only` variant: Document Intelligence's own answer, in our shape."""
    by_name = {field.name: field for field in fields}
    extracted = {}
    for name, kind in FIELD_KINDS.items():
        di = by_name.get(DI_FIELD_NAMES[name])
        if di is None:
            extracted[name] = FieldValue()
            continue
        value = normalise.canonical(kind, di.value)
        extracted[name] = FieldValue(
            value=value,
            page=di.page,
            source_text=di.value,
            di_value=value,
            di_confidence=di.confidence,
            flags=[] if value is not None else [FLAG_UNPARSEABLE],
        )

    items: dict[int, dict[str, str]] = {}
    for field in fields:
        match = _ITEM_FIELD.match(field.name)
        if match:
            items.setdefault(int(match.group(1)), {})[match.group(2)] = field.value
    lines = [
        ExtractedLine(
            description=" ".join(item.get("Description", "").split()),
            quantity=normalise.canonical_number(item.get("Quantity")),
            unit_price=normalise.canonical(normalise.AMOUNT, item.get("UnitPrice")),
            vat_rate=normalise.canonical_number(item.get("TaxRate")),
            line_total=normalise.canonical(normalise.AMOUNT, item.get("Amount")),
        )
        for _, item in sorted(items.items())
    ]
    return ExtractedInvoice(fields=extracted, line_items=lines)


def build_user_prompt(reading: ReadResult, di_fields: list[ReadField] | None) -> str:
    pages = "\n".join(f"[page {page.number}]\n{page.text}" for page in reading.pages)
    prompt = f"<document_text>\n{pages}\n</document_text>"
    if di_fields:
        lines = "\n".join(
            f"{field.name}: {field.value} (confidence {field.confidence:.2f})"
            for field in di_fields
        )
        prompt += f"\n<document_intelligence_fields>\n{lines}\n</document_intelligence_fields>"
    return prompt


def _field_from_llm(kind: str, llm: LlmField, di: FieldValue | None) -> FieldValue:
    value = normalise.canonical(kind, llm.value)
    flags = []
    if value is None and llm.value and llm.value.strip():
        flags.append(FLAG_UNPARSEABLE)
    # The model normalises (1.234,56 -> 1234.56). Check its work against what it
    # says was printed, with our own explicit Dutch and English parsing.
    if value is not None and kind in _CHECKED_AGAINST_SOURCE:
        from_source = normalise.canonical(kind, llm.source_text)
        if from_source is not None and from_source != value:
            flags.append(FLAG_NORMALISATION_MISMATCH)
    field = FieldValue(value=value, page=llm.page, source_text=llm.source_text, flags=flags)
    if di is not None and di.di_value is not None:
        field.di_value = di.di_value
        field.di_confidence = di.di_confidence
        if value != di.di_value:
            field.flags.append(FLAG_DI_DISAGREES)
    return field


def merge(llm: LlmInvoice, di_fields: list[ReadField] | None) -> ExtractedInvoice:
    """Canonicalise the model's answer and, when given, compare it with Document Intelligence."""
    di = di_fields_to_invoice(di_fields).fields if di_fields else {}
    fields = {
        name: _field_from_llm(kind, getattr(llm, name), di.get(name))
        for name, kind in FIELD_KINDS.items()
    }
    lines = [
        ExtractedLine(
            description=" ".join(line.description.split()),
            quantity=normalise.canonical_number(line.quantity),
            unit_price=normalise.canonical(normalise.AMOUNT, line.unit_price),
            vat_rate=normalise.canonical_number(line.vat_rate),
            line_total=normalise.canonical(normalise.AMOUNT, line.line_total),
        )
        for line in llm.line_items
    ]
    return ExtractedInvoice(fields=fields, line_items=lines)


async def extract_with_model(
    model: ChatModel, prompt: Prompt, reading: ReadResult, di_fields: list[ReadField] | None
) -> tuple[ExtractedInvoice, ModelUsage]:
    """`llm_only` when `di_fields` is None, `combined` otherwise."""
    user = build_user_prompt(reading, di_fields)
    result = await model.structured(system=prompt.text, user=user, schema=LlmInvoice)
    return merge(result.value, di_fields), result.usage
