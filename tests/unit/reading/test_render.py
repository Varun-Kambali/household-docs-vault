import pypdfium2 as pdfium
import pytest

from household_vault.reading.render import (
    DamagedFileError,
    LockedPdfError,
    page_count,
    png_bytes,
    render_page,
)


def test_render_closes_the_document(monkeypatch, clean_pdf_bytes):
    closed = []
    monkeypatch.setattr(pdfium.PdfDocument, "close", lambda self: closed.append(True))
    render_page(clean_pdf_bytes, 0)
    assert closed == [True]


def test_render_gives_an_rgb_image_at_the_dpi(clean_pdf_bytes):
    image = render_page(clean_pdf_bytes, 0, dpi=144)
    assert image.mode == "RGB" and image.size == (600, 800)
    assert png_bytes(image).startswith(b"\x89PNG")


def test_locked_pdf_needs_its_password(locked_pdf_bytes):
    with pytest.raises(LockedPdfError):
        page_count(locked_pdf_bytes)
    assert page_count(locked_pdf_bytes, password="pw") == 1
    assert render_page(locked_pdf_bytes, 0, password="pw").mode == "RGB"


def test_garbage_is_a_damaged_file():
    with pytest.raises(DamagedFileError):
        page_count(b"not a pdf")
