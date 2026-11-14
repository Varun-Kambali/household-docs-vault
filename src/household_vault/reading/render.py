"""Turn a PDF page into an image. The PDF is opened from bytes and always closed."""

from __future__ import annotations

import io

import pypdfium2 as pdfium
from PIL import Image


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
