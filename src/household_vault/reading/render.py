"""Turn a PDF page into an image. The PDF is opened from bytes and always closed."""

from __future__ import annotations

import io

import pypdfium2 as pdfium
from PIL import Image

from household_vault.reading.lines import Line, line_lang


class LockedPdfError(Exception):
    """The PDF needs a password, or the one given is wrong."""


class DamagedFileError(Exception):
    """The file is not a readable PDF."""


def _open(data: bytes, password: str | None) -> pdfium.PdfDocument:
    try:
        return pdfium.PdfDocument(data, password=password)
    except pdfium.PdfiumError as exc:
        # the message is pdfium's own and never carries the password
        if "password" in str(exc).lower():
            raise LockedPdfError("the PDF needs a password") from None
        raise DamagedFileError("the file could not be read as a PDF") from None


def page_count(data: bytes, password: str | None = None) -> int:
    pdf = _open(data, password)
    try:
        return len(pdf)
    finally:
        pdf.close()


def render_page(
    data: bytes, index: int, *, dpi: int = 200, password: str | None = None
) -> Image.Image:
    pdf = _open(data, password)
    try:
        image: Image.Image = pdf[index].render(scale=dpi / 72).to_pil().convert("RGB")
        return image
    finally:
        pdf.close()


def png_bytes(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def text_layer(data: bytes, index: int, password: str | None = None) -> tuple[int, int, list[Line]]:
    """The page's text layer as (width, height in points, lines), boxes as fractions of the page
    with the origin top left. Empty when the page has no text layer."""
    pdf = _open(data, password)
    try:
        page = pdf[index]
        width, height = page.get_size()
        textpage = page.get_textpage()
        lines: list[Line] = []
        for i in range(textpage.count_rects()):
            left, bottom, right, top = textpage.get_rect(i)
            text = textpage.get_text_bounded(left, bottom, right, top).strip()
            if not text or width <= 0 or height <= 0:
                continue
            lines.append(
                Line(
                    text=text,
                    page=index,
                    bbox=(
                        max(0.0, left / width),
                        max(0.0, 1 - top / height),
                        min(1.0, right / width),
                        min(1.0, 1 - bottom / height),
                    ),
                    lang=line_lang(text),
                )
            )
        return round(width), round(height), lines
    finally:
        pdf.close()
