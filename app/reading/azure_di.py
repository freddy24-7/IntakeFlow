"""Azure Document Intelligence behind the DocumentReader interface."""

from typing import Any

from azure.ai.documentintelligence.aio import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeDocumentRequest
from azure.identity.aio import DefaultAzureCredential

from app.reading.interfaces import PageText, ReadField, ReadResult

READ_MODEL = "prebuilt-read"
INVOICE_MODEL = "prebuilt-invoice"
# Where a typed field keeps its value, by Document Intelligence field type.
_TYPED_VALUES = {
    "string": "valueString",
    "date": "valueDate",
    "number": "valueNumber",
    "integer": "valueInteger",
    "countryRegion": "valueCountryRegion",
}


class AzureDocumentReader:
    def __init__(self, client: Any, credential: Any = None) -> None:
        self._client = client
        self._credential = credential

    @classmethod
    def connect(cls, *, endpoint: str, retries: int = 5) -> "AzureDocumentReader":
        """Keyless sign-in. The SDK retries throttled and failed calls with backoff."""
        credential = DefaultAzureCredential()
        client = DocumentIntelligenceClient(
            endpoint=endpoint, credential=credential, retry_total=retries
        )
        return cls(client, credential)

    async def _analyze(self, model: str, content: bytes) -> dict[str, Any]:
        poller = await self._client.begin_analyze_document(
            model, AnalyzeDocumentRequest(bytes_source=content)
        )
        result: dict[str, Any] = (await poller.result()).as_dict()
        return result

    async def read_text(self, content: bytes) -> ReadResult:
        return to_read_result(await self._analyze(READ_MODEL, content))

    async def read_invoice_fields(self, content: bytes) -> ReadResult:
        return to_read_result(await self._analyze(INVOICE_MODEL, content))

    async def close(self) -> None:
        await self._client.close()
        if self._credential is not None:
            await self._credential.close()


def to_read_result(result: dict[str, Any]) -> ReadResult:
    """Convert an analyze result (as a dict) to our own shape."""
    pages = [
        PageText(
            number=page["pageNumber"],
            text="\n".join(line["content"] for line in page.get("lines", [])),
        )
        for page in result.get("pages", [])
    ]
    fields: list[ReadField] = []
    documents = result.get("documents") or []
    if documents:
        _flatten(documents[0].get("fields", {}), "", fields)
    return ReadResult(pages=pages, fields=fields, raw=_without_words(result))


def _flatten(fields: dict[str, Any], prefix: str, out: list[ReadField]) -> None:
    """Flatten nested fields to names like `InvoiceTotal` and `Items[0].Amount`."""
    for name, field in fields.items():
        kind = field.get("type")
        if kind == "array":
            for index, item in enumerate(field.get("valueArray", [])):
                _flatten(item.get("valueObject", {}), f"{prefix}{name}[{index}].", out)
            continue
        if kind == "object":
            _flatten(field.get("valueObject", {}), f"{prefix}{name}.", out)
            continue

        regions = field.get("boundingRegions") or [{}]
        page = int(regions[0].get("pageNumber", 1))
        confidence = float(field.get("confidence", 0.0))
        if kind == "currency":
            money = field.get("valueCurrency", {})
            value = str(money.get("amount", field.get("content", "")))
            code = money.get("currencyCode")
            # The invoice total's currency doubles as the document's currency.
            if code and f"{prefix}{name}" == "InvoiceTotal":
                out.append(ReadField("CurrencyCode", str(code), confidence, page))
        else:
            value = str(field.get(_TYPED_VALUES.get(kind, ""), field.get("content", "")))
        out.append(ReadField(f"{prefix}{name}", value, confidence, page))


def _without_words(result: dict[str, Any]) -> dict[str, Any]:
    """Keep the raw result for debugging (PRD F3), minus the per-word boxes that
    make up most of its size. Lines, paragraphs and fields stay."""
    pages = [{k: v for k, v in page.items() if k != "words"} for page in result.get("pages", [])]
    return {**result, "pages": pages}
