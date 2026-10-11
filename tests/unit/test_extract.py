from app.agents import extract
from app.agents.classify import classify
from app.agents.prompts import CLASSIFY, EXTRACT_INVOICE, load_prompt
from app.agents.schema import (
    FIELD_KINDS,
    FLAG_DI_DISAGREES,
    FLAG_NORMALISATION_MISMATCH,
    FLAG_UNPARSEABLE,
    ClassificationAnswer,
    LlmField,
    LlmInvoice,
    LlmLineItem,
)
from app.inference.fakes import FakeChatModel
from app.reading.interfaces import PageText, ReadField, ReadResult

READING = ReadResult(pages=[PageText(1, "FACTUUR F2026-0001"), PageText(2, "Totaal € 1.234,56")])
DI_FIELDS = [
    ReadField("VendorName", "Arens Software B.V.", 0.95, 1),
    ReadField("VendorTaxId", "NL 942755630B73", 0.9, 1),
    ReadField("PaymentDetails[0].IBAN", "NL18 HAVN 1028 4398 63", 0.8, 1),
    ReadField("InvoiceId", "F2026-0001", 0.97, 1),
    ReadField("InvoiceDate", "2026-03-20", 0.96, 1),
    ReadField("DueDate", "2026-04-19", 0.96, 1),
    ReadField("CurrencyCode", "EUR", 0.9, 2),
    ReadField("SubTotal", "1020.3", 0.9, 2),
    ReadField("TotalTax", "214.26", 0.9, 2),
    ReadField("InvoiceTotal", "1234.56", 0.9, 2),
    ReadField("Items[1].Description", "Tweede regel", 0.8, 1),
    ReadField("Items[1].Amount", "20.30", 0.8, 1),
    ReadField("Items[0].Description", "Eerste  regel", 0.8, 1),
    ReadField("Items[0].Quantity", "2.5", 0.8, 1),
    ReadField("Items[0].UnitPrice", "400", 0.8, 1),
    ReadField("Items[0].TaxRate", "21%", 0.8, 1),
    ReadField("Items[0].Amount", "1000.00", 0.8, 1),
]


def _field(value: str | None, source: str | None = None, page: int | None = 1) -> LlmField:
    return LlmField(value=value, page=page, source_text=source if source else value)


def _llm_invoice(**overrides: LlmField) -> LlmInvoice:
    fields = {
        "supplier_name": _field("Arens Software B.V."),
        "supplier_vat_number": _field("NL942755630B73"),
        "iban": _field("NL18HAVN1028439863", "NL18 HAVN 1028 4398 63"),
        "invoice_number": _field("F2026-0001"),
        "invoice_date": _field("2026-03-20", "20-03-2026"),
        "due_date": _field("2026-04-19", "19 april 2026"),
        "currency": _field("EUR", "€"),
        "subtotal": _field("1020.30", "€ 1.020,30", 2),
        "vat": _field("214.26", "€ 214,26", 2),
        "total": _field("1234.56", "€ 1.234,56", 2),
        "purchase_order_reference": _field(None, None, None),
    }
    fields.update(overrides)
    line = LlmLineItem(
        description="Eerste regel",
        quantity="2.5",
        unit_price="400.00",
        vat_rate="21",
        line_total="1000.00",
    )
    return LlmInvoice(**fields, line_items=[line])


def test_di_only_maps_fields_and_orders_line_items() -> None:
    invoice = extract.di_fields_to_invoice(DI_FIELDS)

    assert set(invoice.fields) == set(FIELD_KINDS)
    assert invoice.fields["iban"].value == "NL18HAVN1028439863"
    assert invoice.fields["supplier_vat_number"].value == "NL942755630B73"
    assert invoice.fields["subtotal"].value == "1020.30"
    assert invoice.fields["total"].page == 2
    assert invoice.fields["total"].di_confidence == 0.9
    # Not returned by Document Intelligence: empty, not invented.
    assert invoice.fields["purchase_order_reference"].value is None
    assert [line.description for line in invoice.line_items] == ["Eerste regel", "Tweede regel"]
    first = invoice.line_items[0]
    assert (first.quantity, first.unit_price, first.vat_rate, first.line_total) == (
        "2.5",
        "400.00",
        "21",
        "1000.00",
    )


def test_di_value_that_cannot_be_read_is_flagged() -> None:
    invoice = extract.di_fields_to_invoice([ReadField("InvoiceDate", "next week", 0.4, 1)])

    assert invoice.fields["invoice_date"].value is None
    assert invoice.fields["invoice_date"].flags == [FLAG_UNPARSEABLE]


def test_llm_only_has_no_di_values_or_flags() -> None:
    invoice = extract.merge(_llm_invoice(), None)

    assert invoice.fields["total"].value == "1234.56"
    assert invoice.fields["total"].source_text == "€ 1.234,56"
    assert invoice.fields["invoice_date"].value == "2026-03-20"
    assert all(field.di_value is None and field.flags == [] for field in invoice.fields.values())
    assert invoice.line_items[0].quantity == "2.5"


def test_combined_agrees_without_flags() -> None:
    invoice = extract.merge(_llm_invoice(), DI_FIELDS)

    assert all(field.flags == [] for field in invoice.fields.values())
    assert invoice.fields["total"].di_value == "1234.56"
    assert invoice.fields["total"].di_confidence == 0.9


def test_combined_flags_a_field_where_the_two_disagree() -> None:
    invoice = extract.merge(_llm_invoice(invoice_number=_field("F2026-0007")), DI_FIELDS)

    assert invoice.fields["invoice_number"].value == "F2026-0007"
    assert invoice.fields["invoice_number"].di_value == "F2026-0001"
    assert invoice.fields["invoice_number"].flags == [FLAG_DI_DISAGREES]
    assert invoice.fields["total"].flags == []


def test_wrong_normalisation_of_a_dutch_amount_is_flagged() -> None:
    """The classic error: reading 1.234,56 as 1.23456 or 1.234."""
    wrong = _field("1.23", "€ 1.234,56", 2)

    invoice = extract.merge(_llm_invoice(total=wrong), None)

    assert invoice.fields["total"].value == "1.23"
    assert invoice.fields["total"].flags == [FLAG_NORMALISATION_MISMATCH]


def test_wrong_normalisation_of_a_day_first_date_is_flagged() -> None:
    swapped = _field("2026-04-03", "04-03-2026")

    invoice = extract.merge(_llm_invoice(invoice_date=swapped), None)

    assert invoice.fields["invoice_date"].flags == [FLAG_NORMALISATION_MISMATCH]


def test_value_the_model_could_not_normalise_is_flagged() -> None:
    invoice = extract.merge(_llm_invoice(due_date=_field("binnen 30 dagen")), None)

    assert invoice.fields["due_date"].value is None
    assert invoice.fields["due_date"].flags == [FLAG_UNPARSEABLE]


def test_user_prompt_has_pages_and_optional_di_section() -> None:
    without = extract.build_user_prompt(READING, None)
    with_di = extract.build_user_prompt(READING, DI_FIELDS[:1])

    assert "[page 1]\nFACTUUR F2026-0001" in without
    assert "[page 2]" in without
    assert "document_intelligence_fields" not in without
    assert "VendorName: Arens Software B.V. (confidence 0.95)" in with_di


async def test_extract_with_model_sends_the_prompt_and_returns_usage() -> None:
    model = FakeChatModel(answers={LlmInvoice: _llm_invoice()})
    prompt = load_prompt(EXTRACT_INVOICE)

    invoice, usage = await extract.extract_with_model(model, prompt, READING, DI_FIELDS)

    assert invoice.fields["total"].value == "1234.56"
    assert usage.model == "fake-chat"
    assert model.calls[0].system == prompt.text
    assert "document_intelligence_fields" in model.calls[0].user


async def test_classify_clamps_confidence_and_limits_the_text() -> None:
    model = FakeChatModel(
        answers={ClassificationAnswer: ClassificationAnswer(label="invoice", confidence=1.7)}
    )
    long_reading = ReadResult(pages=[PageText(1, "x" * 20_000)])

    answer, _ = await classify(model, load_prompt(CLASSIFY), long_reading)

    assert (answer.label, answer.confidence) == ("invoice", 1.0)
    assert len(model.calls[0].user) < 7000


def test_prompts_are_versioned_files() -> None:
    assert load_prompt(CLASSIFY).version == "classify_v1"
    assert "1.234,56" in load_prompt(EXTRACT_INVOICE).text
