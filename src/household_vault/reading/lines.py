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
