"""OCR engine wrappers for the reading spike.

Every engine returns lines with boxes normalised to 0..1, origin top-left, (x0, y0, x1, y1),
the same convention as the ground truth.
"""

from __future__ import annotations

import importlib.metadata
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from PIL import Image


@dataclass(frozen=True)
class OcrLine:
    text: str
    bbox: tuple[float, float, float, float]
    confidence: float | None


class Engine(Protocol):
    name: str

    def read(self, image: Path) -> list[OcrLine]: ...


class EngineUnavailable(Exception):
    """The engine's package, binary or model is not installed."""


def _version(dist: str) -> str:
    try:
        return importlib.metadata.version(dist)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


class AppleVision:
    """Apple's built-in Vision text recogniser through ocrmac, accurate mode."""

    name = "apple-vision"

    def __init__(self) -> None:
        try:
            from ocrmac import ocrmac
        except ImportError as exc:
            raise EngineUnavailable("not installed") from exc
        self._ocrmac = ocrmac

    @property
    def version(self) -> str:
        return f"ocrmac {_version('ocrmac')}"

    def read(self, image: Path) -> list[OcrLine]:
        with Image.open(image) as img:
            rgb = img.convert("RGB")
        results = self._ocrmac.text_from_image(rgb, recognition_level="accurate")
        lines = []
        for text, conf, (x, y, w, h) in results:
            # Vision boxes are (x, y, w, h) with the origin at the bottom left.
            lines.append(OcrLine(text, (x, 1 - (y + h), x + w, 1 - y), float(conf)))
        return lines


class Tesseract:
    """Tesseract 5 through pytesseract; words are grouped back into lines."""

    name = "tesseract"

    def __init__(self) -> None:
        try:
            import pytesseract
        except ImportError as exc:
            raise EngineUnavailable("not installed") from exc
        if shutil.which("tesseract") is None:
            raise EngineUnavailable("not installed")
        self._pt = pytesseract

    @property
    def version(self) -> str:
        return f"tesseract {self._pt.get_tesseract_version()}"

    def read(self, image: Path) -> list[OcrLine]:
        with Image.open(image) as img:
            rgb = img.convert("RGB")
        width, height = rgb.size
        d = self._pt.image_to_data(rgb, lang="eng", output_type=self._pt.Output.DICT)
        groups: dict[tuple[int, int, int, int], list[int]] = {}
        for i, text in enumerate(d["text"]):
            if d["level"][i] != 5 or not text.strip() or d["conf"][i] < 0:
                continue
            key = (d["page_num"][i], d["block_num"][i], d["par_num"][i], d["line_num"][i])
            groups.setdefault(key, []).append(i)
        lines = []
        for idx in groups.values():
            x0 = min(d["left"][i] for i in idx)
            y0 = min(d["top"][i] for i in idx)
            x1 = max(d["left"][i] + d["width"][i] for i in idx)
            y1 = max(d["top"][i] + d["height"][i] for i in idx)
            conf = sum(d["conf"][i] for i in idx) / len(idx) / 100
            text = " ".join(d["text"][i] for i in idx)
            lines.append(OcrLine(text, (x0 / width, y0 / height, x1 / width, y1 / height), conf))
        return lines


class PaddleOcr:
    """PaddleOCR 3.x text detection plus recognition (English models)."""

    name = "paddleocr"

    def __init__(self) -> None:
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise EngineUnavailable("not installed") from exc
        self._ocr = PaddleOCR(
            lang="en",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )

    @property
    def version(self) -> str:
        return f"paddleocr {_version('paddleocr')}"

    def read(self, image: Path) -> list[OcrLine]:
        with Image.open(image) as img:
            width, height = img.size
        lines = []
        for res in self._ocr.predict(str(image)):
            data = res.get("res", res)
            for text, score, box in zip(
                data["rec_texts"], data["rec_scores"], data["rec_boxes"], strict=True
            ):
                x0, y0, x1, y1 = (float(v) for v in box)
                lines.append(
                    OcrLine(text, (x0 / width, y0 / height, x1 / width, y1 / height), float(score))
                )
        return lines


ENGINES: dict[str, type] = {
    AppleVision.name: AppleVision,
    Tesseract.name: Tesseract,
    PaddleOcr.name: PaddleOcr,
}
