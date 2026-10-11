"""Turns a digital PDF into something that looks scanned: an image per page, no text layer."""

import io

import pypdfium2 as pdfium
from PIL import Image, ImageFilter
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

SCAN_DPI = 130


def rasterise(pdf: bytes, skew_degrees: float = 0.0) -> bytes:
    """Render each page to a greyscale image, optionally rotated, and wrap it in a new PDF."""
    page_width, page_height = float(A4[0]), float(A4[1])
    source = pdfium.PdfDocument(pdf)
    buffer = io.BytesIO()
    canvas = Canvas(buffer, pagesize=A4, invariant=1)
    try:
        for index in range(len(source)):
            image: Image.Image = source[index].render(scale=SCAN_DPI / 72).to_pil().convert("L")
            if skew_degrees:
                image = image.rotate(
                    skew_degrees, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=255
                )
            image = image.filter(ImageFilter.GaussianBlur(0.6))
            # Fit the (possibly larger, rotated) image inside the page.
            scale = min(page_width / image.width, page_height / image.height)
            width, height = image.width * scale, image.height * scale
            canvas.drawImage(
                ImageReader(image),
                (page_width - width) / 2,
                (page_height - height) / 2,
                width=width,
                height=height,
            )
            canvas.showPage()
    finally:
        source.close()
    canvas.save()
    return buffer.getvalue()
