"""Fake document reader, so the pipeline runs without Document Intelligence."""

import hashlib
from dataclasses import dataclass, field

import pypdfium2 as pdfium

from app.reading.interfaces import PageText, ReadField, ReadResult


def content_key(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


@dataclass
class FakeDocumentReader:
    """Returns canned results per file (keyed by content hash).

    Without a canned result, `read_text` falls back to the PDF's own text layer.
    That works for digital PDFs and returns empty pages for scans, which is the
    honest behaviour for a fake: it does no OCR.
    """

    texts: dict[str, ReadResult] = field(default_factory=dict)
    invoice_fields: dict[str, list[ReadField]] = field(default_factory=dict)

    async def read_text(self, content: bytes) -> ReadResult:
        canned = self.texts.get(content_key(content))
        if canned is not None:
            return canned
        return ReadResult(pages=extract_text_layer(content), raw={"source": "pdf-text-layer"})

    async def read_invoice_fields(self, content: bytes) -> ReadResult:
        text = await self.read_text(content)
        fields = self.invoice_fields.get(content_key(content), [])
        return ReadResult(pages=text.pages, fields=fields, raw={"source": "fake"})


def extract_text_layer(content: bytes) -> list[PageText]:
    document = pdfium.PdfDocument(content)
    try:
        pages = []
        for index in range(len(document)):
            text_page = document[index].get_textpage()
            pages.append(PageText(number=index + 1, text=text_page.get_text_range()))
        return pages
    finally:
        document.close()
