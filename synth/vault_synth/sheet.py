"""A drawing surface that records where every printed line lands.

The boxes are taken from the same coordinates the text is drawn at, so they are the ground truth
by construction, not by detection.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from reportlab.lib.colors import Color, HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from vault_synth.model import Lang, LineBox

FONT_DIR = Path(__file__).resolve().parent.parent / "fonts"
KN_FONT = "NotoSansKannada"
_registered = False


def _register_fonts() -> None:
    global _registered
    if not _registered:
        pdfmetrics.registerFont(TTFont(KN_FONT, str(FONT_DIR / "NotoSansKannada-Regular.ttf")))
        _registered = True


@dataclass
class Truth:
    """What a template says about the document it drew."""

    person: str
    fields: dict[str, str] = field(default_factory=dict)
    printed: dict[str, str] = field(default_factory=dict)
    field_lines: dict[str, list[int]] = field(default_factory=dict)

    def add(self, name: str, value: str, printed: str, idx: list[int]) -> None:
        self.fields[name] = value
        self.printed[name] = printed
        self.field_lines[name] = idx


class Sheet:
    def __init__(self, path: Path, width: float, height: float) -> None:
        _register_fonts()
        self.w = width
        self.h = height
        # invariant=1 keeps dates and ids out of the PDF so reruns give identical bytes
        self.c = Canvas(str(path), pagesize=(width, height), invariant=1)
        self.lines: list[LineBox] = []

    def put(
        self,
        text: str,
        x: float,
        top: float,
        size: float = 10,
        *,
        font: str = "Helvetica",
        lang: Lang = "en",
        color: str | Color = "#111111",
        align: Literal["l", "r", "c"] = "l",
    ) -> int:
        """Draw one printed line with its top edge at `top` (points from the page top)."""
        if lang == "kn":
            font = KN_FONT
        width = pdfmetrics.stringWidth(text, font, size)
        left = x if align == "l" else x - width if align == "r" else x - width / 2
        baseline = top + size * 0.82
        self.c.setFillColor(HexColor(color) if isinstance(color, str) else color)
        self.c.setFont(font, size)
        self.c.drawString(left, self.h - baseline, text)
        # Kannada glyphs reach lower than Latin ones, so give them a taller box
        depth = size * (1.35 if lang == "kn" else 1.1)
        box = (
            max(0.0, left / self.w),
            max(0.0, top / self.h),
            min(1.0, (left + width) / self.w),
            min(1.0, (top + depth) / self.h),
        )
        self.lines.append(LineBox(text=text, page=0, bbox=box, lang=lang))
        return len(self.lines) - 1

    def rect(
        self,
        x: float,
        top: float,
        w: float,
        h: float,
        *,
        fill: str | None = None,
        stroke: str | None = "#999999",
        width: float = 0.6,
    ) -> None:
        if fill:
            self.c.setFillColor(HexColor(fill))
        if stroke:
            self.c.setStrokeColor(HexColor(stroke))
            self.c.setLineWidth(width)
        self.c.rect(x, self.h - top - h, w, h, stroke=1 if stroke else 0, fill=1 if fill else 0)

    def hline(
        self, x0: float, x1: float, top: float, color: str = "#bbbbbb", width: float = 0.5
    ) -> None:
        self.c.setStrokeColor(HexColor(color))
        self.c.setLineWidth(width)
        self.c.line(x0, self.h - top, x1, self.h - top)

    def save(self) -> None:
        self.c.showPage()
        self.c.save()
