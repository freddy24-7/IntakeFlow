"""The Azure adapters, tested without Azure: the SDK client is replaced by a stub.

Whether the real services answer in the shapes assumed here is checked by the
tests marked `azure`, which run only on request.
"""

from typing import Any

import pytest
from pydantic import BaseModel

from app.inference.azure_openai import AzureOpenAIChatModel, ModelOutputError
from app.reading.azure_di import AzureDocumentReader, to_read_result

ANALYZE_RESULT: dict[str, Any] = {
    "modelId": "prebuilt-invoice",
    "content": "FACTUUR ...",
    "pages": [
        {
            "pageNumber": 1,
            "lines": [{"content": "FACTUUR"}, {"content": "Totaal € 1.234,56"}],
            "words": [{"content": "FACTUUR", "polygon": [0, 0, 1, 1]}],
        },
        {"pageNumber": 2, "lines": []},
    ],
    "documents": [
        {
            "docType": "invoice",
            "fields": {
                "VendorName": {
                    "type": "string",
                    "valueString": "Arens Software B.V.",
                    "content": "Arens Software B.V.",
                    "confidence": 0.93,
                    "boundingRegions": [{"pageNumber": 1}],
                },
                "InvoiceDate": {
                    "type": "date",
                    "valueDate": "2026-03-20",
                    "content": "20-03-2026",
                    "confidence": 0.9,
                    "boundingRegions": [{"pageNumber": 1}],
                },
                "InvoiceTotal": {
                    "type": "currency",
                    "valueCurrency": {"amount": 1234.56, "currencyCode": "EUR"},
                    "content": "€ 1.234,56",
                    "confidence": 0.88,
                    "boundingRegions": [{"pageNumber": 2}],
                },
                "PaymentDetails": {
                    "type": "array",
                    "valueArray": [
                        {
                            "type": "object",
                            "valueObject": {
                                "IBAN": {
                                    "type": "string",
                                    "valueString": "NL18HAVN1028439863",
                                    "content": "NL18 HAVN 1028 4398 63",
                                    "confidence": 0.8,
                                }
                            },
                        }
                    ],
                },
                "Items": {
                    "type": "array",
                    "valueArray": [
                        {
                            "type": "object",
                            "valueObject": {
                                "Description": {
                                    "type": "string",
                                    "valueString": "Opslag",
                                    "confidence": 0.9,
                                },
                                "Quantity": {
                                    "type": "number",
                                    "valueNumber": 17,
                                    "confidence": 0.9,
                                },
                                "Amount": {
                                    "type": "currency",
                                    "valueCurrency": {"amount": 181.9},
                                    "confidence": 0.9,
                                },
                            },
                        }
                    ],
                },
            },
        }
    ],
}


def test_analyze_result_becomes_pages_and_flat_fields() -> None:
    result = to_read_result(ANALYZE_RESULT)

    assert [(page.number, page.text) for page in result.pages] == [
        (1, "FACTUUR\nTotaal € 1.234,56"),
        (2, ""),
    ]
    fields = {field.name: field for field in result.fields}
    assert fields["VendorName"].value == "Arens Software B.V."
    assert fields["InvoiceDate"].value == "2026-03-20"
    assert (fields["InvoiceTotal"].value, fields["InvoiceTotal"].page) == ("1234.56", 2)
    assert fields["InvoiceTotal"].confidence == 0.88
    assert fields["CurrencyCode"].value == "EUR"
    assert fields["PaymentDetails[0].IBAN"].value == "NL18HAVN1028439863"
    assert fields["Items[0].Description"].value == "Opslag"
    assert fields["Items[0].Quantity"].value == "17"
    assert fields["Items[0].Amount"].value == "181.9"


def test_raw_result_is_kept_without_word_boxes() -> None:
    result = to_read_result(ANALYZE_RESULT)

    assert result.raw["modelId"] == "prebuilt-invoice"
    assert "words" not in result.raw["pages"][0]
    assert result.raw["pages"][0]["lines"][0] == {"content": "FACTUUR"}
    assert "words" in ANALYZE_RESULT["pages"][0]  # the input is not changed


def test_text_only_result_has_no_fields() -> None:
    assert to_read_result({"pages": [{"pageNumber": 1, "lines": []}]}).fields == []


class _Poller:
    def __init__(self, result: dict[str, Any]) -> None:
        self._result = result

    async def result(self) -> Any:
        outer = self

        class _Result:
            def as_dict(self) -> dict[str, Any]:
                return outer._result

        return _Result()


class _DiClient:
    def __init__(self) -> None:
        self.models: list[str] = []

    async def begin_analyze_document(self, model: str, body: Any) -> _Poller:
        self.models.append(model)
        return _Poller(ANALYZE_RESULT)


async def test_reader_calls_the_right_model_for_each_pass() -> None:
    client = _DiClient()
    reader = AzureDocumentReader(client)

    await reader.read_text(b"%PDF-")
    fields = await reader.read_invoice_fields(b"%PDF-")

    assert client.models == ["prebuilt-read", "prebuilt-invoice"]
    assert len(fields.fields) == 8


class Answer(BaseModel):
    label: str


class _Raw:
    def __init__(self) -> None:
        self.usage_metadata = {"input_tokens": 120, "output_tokens": 8, "total_tokens": 128}


class _Llm:
    def __init__(self, parsed: Any) -> None:
        self.parsed = parsed
        self.requests: list[Any] = []
        self.options: dict[str, Any] = {}

    def with_structured_output(self, schema: Any, **options: Any) -> "_Llm":
        self.options = {"schema": schema, **options}
        return self

    async def ainvoke(self, messages: Any) -> dict[str, Any]:
        self.requests.append(messages)
        return {"parsed": self.parsed, "raw": _Raw(), "parsing_error": None}


async def test_chat_model_asks_for_strict_structured_output_and_reports_usage() -> None:
    llm = _Llm(Answer(label="invoice"))
    model = AzureOpenAIChatModel(llm, "gpt-4.1-mini")

    result = await model.structured(system="classify", user="text", schema=Answer)

    assert result.value == Answer(label="invoice")
    assert llm.options == {
        "schema": Answer,
        "method": "json_schema",
        "strict": True,
        "include_raw": True,
    }
    assert llm.requests == [[("system", "classify"), ("human", "text")]]
    assert (result.usage.model, result.usage.input_tokens, result.usage.output_tokens) == (
        "gpt-4.1-mini",
        120,
        8,
    )
    assert result.usage.latency_ms >= 0


async def test_answer_outside_the_schema_is_an_error_without_document_text() -> None:
    model = AzureOpenAIChatModel(_Llm(None), "gpt-4.1")

    with pytest.raises(ModelOutputError) as error:
        await model.structured(system="s", user="secret invoice text", schema=Answer)

    assert "secret" not in str(error.value)
