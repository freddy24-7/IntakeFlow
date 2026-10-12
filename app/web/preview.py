"""Renders PDF pages as images for the review page.

An image per page works in every browser and needs no PDF viewer. Embedded
PDFs do not display in all of them.
"""

import io

import pypdfium2 as pdfium

PREVIEW_DPI = 110


def page_count(content: bytes) -> int:
    document = pdfium.PdfDocument(content)
    try:
        return len(document)
    finally:
        document.close()


def render_page(content: bytes, number: int) -> bytes | None:
    """Page `number` (1-based) as PNG, or None when the document has no such page."""
    document = pdfium.PdfDocument(content)
    try:
        if not 1 <= number <= len(document):
            return None
        image = document[number - 1].render(scale=PREVIEW_DPI / 72).to_pil()
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()
    finally:
        document.close()
