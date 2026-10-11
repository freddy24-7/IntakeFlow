"""Schemas for classification and invoice extraction.

There are two shapes on purpose. `Llm*` is what the model is asked to fill in:
flat, text-only and every property required, which is what strict structured
output needs. `ExtractedInvoice` is what the application stores: canonical
values plus where each came from and what was flagged.
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.agents import normalise

DocumentLabel = Literal["invoice", "credit_note", "contract", "other"]
INVOICE_LABELS = ("invoice", "credit_note")

# Field name -> kind of value, in the order of PRD F4.
FIELD_KINDS: dict[str, str] = {
    "supplier_name": normalise.TEXT,
    "supplier_vat_number": normalise.VAT_NUMBER,
    "iban": normalise.IBAN,
    "invoice_number": normalise.TEXT,
    "invoice_date": normalise.DATE,
    "due_date": normalise.DATE,
    "currency": normalise.CURRENCY,
    "subtotal": normalise.AMOUNT,
    "vat": normalise.AMOUNT,
    "total": normalise.AMOUNT,
    "purchase_order_reference": normalise.TEXT,
}

# Flags on a field. Scoring and the review page use them in later stages.
FLAG_DI_DISAGREES = "di_disagrees"
FLAG_UNPARSEABLE = "unparseable"
FLAG_NORMALISATION_MISMATCH = "normalisation_mismatch"


class ClassificationAnswer(BaseModel):
    label: DocumentLabel
    confidence: float = Field(description="Between 0 and 1.")


class LlmField(BaseModel):
    value: str | None = Field(
        description="Normalised value: dates as YYYY-MM-DD, amounts as 1234.56. Null if absent."
    )
    page: int | None = Field(description="1-based page the value was found on.")
    source_text: str | None = Field(description="The value exactly as printed on the page.")


class LlmLineItem(BaseModel):
    description: str
    quantity: str | None
    unit_price: str | None
    vat_rate: str | None = Field(description="Percentage as a number, for example 21.")
    line_total: str | None


class LlmInvoice(BaseModel):
    supplier_name: LlmField
    supplier_vat_number: LlmField
    iban: LlmField
    invoice_number: LlmField
    invoice_date: LlmField
    due_date: LlmField
    currency: LlmField
    subtotal: LlmField
    vat: LlmField
    total: LlmField
    purchase_order_reference: LlmField
    line_items: list[LlmLineItem]


class FieldValue(BaseModel):
    value: str | None = None  # canonical form, see app.agents.normalise
    page: int | None = None
    source_text: str | None = None
    di_value: str | None = None  # what Document Intelligence read, canonical form
    di_confidence: float | None = None
    flags: list[str] = []


class ExtractedLine(BaseModel):
    description: str
    quantity: str | None = None
    unit_price: str | None = None
    vat_rate: str | None = None
    line_total: str | None = None


class ExtractedInvoice(BaseModel):
    fields: dict[str, FieldValue]
    line_items: list[ExtractedLine]
