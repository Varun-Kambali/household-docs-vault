"""One line of text on a page, as the ground truth, the OCR engines and the reader all see it."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class Line(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    page: int = 0
    # (x0, y0, x1, y1) as fractions of the page, origin top-left
    bbox: tuple[float, float, float, float]
    lang: Literal["en", "kn", "hi"] = "en"
    confidence: float | None = None


class PageText(BaseModel):
    page: int
    width: int
    height: int
    lines: list[Line]


def line_lang(text: str) -> Literal["en", "kn", "hi"]:
    """The script of a line, by its letters: Kannada or Devanagari if either shows, else en."""
    kannada = sum("ಀ" <= c <= "೿" for c in text)
    hindi = sum("ऀ" <= c <= "ॿ" for c in text)
    if kannada and kannada >= hindi:
        return "kn"
    return "hi" if hindi else "en"
