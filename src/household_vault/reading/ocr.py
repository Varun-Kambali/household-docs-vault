"""OCR engines. Apple Vision is the only real one; `ocrmac` is imported when it is built, never
at module level, so this file imports on Linux and in the Docker image."""

from __future__ import annotations

from typing import Protocol

from PIL import Image

from household_vault.reading.lines import Line, line_lang


class EngineUnavailable(Exception):
    """An engine's package or tool is not installed here."""


__all__ = ["AppleVisionOcr", "EngineUnavailable", "OcrEngine", "line_lang", "vision_to_top_left"]


class OcrEngine(Protocol):
    name: str

    def read(self, image: Image.Image, page: int) -> list[Line]: ...


def vision_to_top_left(x: float, y: float, w: float, h: float) -> tuple[float, float, float, float]:
    """Apple Vision box (x, y, w, h), origin bottom left -> (x0, y0, x1, y1), origin top left."""
    return (x, 1 - (y + h), x + w, 1 - y)


class AppleVisionOcr:
    """Apple's built-in Vision text recogniser through ocrmac, accurate mode."""

    name = "apple-vision"

    def __init__(self) -> None:
        try:
            from ocrmac import ocrmac
        except ImportError as exc:
            raise EngineUnavailable("Apple Vision (ocrmac) is not installed here") from exc
        self._ocrmac = ocrmac

    def read(self, image: Image.Image, page: int) -> list[Line]:
        results = self._ocrmac.text_from_image(image.convert("RGB"), recognition_level="accurate")
        return [
            Line(
                text=text,
                page=page,
                bbox=vision_to_top_left(x, y, w, h),
                lang=line_lang(text),
                confidence=float(conf),
            )
            for text, conf, (x, y, w, h) in results
        ]
