"""The two engines the reader runs on: a page reader (text layer or OCR) and the models."""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from typing import Protocol

from PIL import Image, UnidentifiedImageError

from household_vault.config import ConfigError, Settings
from household_vault.doctypes import DocType
from household_vault.intake.sniff import FileKind
from household_vault.reading.cues import best_cue_match
from household_vault.reading.heic import heic_to_png
from household_vault.reading.lines import PageText
from household_vault.reading.ocr import AppleVisionOcr, OcrEngine
from household_vault.reading.ollama import ModelUnavailable, OllamaClient
from household_vault.reading.prompt import (
    CLASSIFY_SYSTEM,
    PROMPT_V2,
    classify_prompt,
    classify_schema,
    schema_for_prompt,
    user_prompt,
)
from household_vault.reading.render import DamagedFileError, page_count, render_page, text_layer
from household_vault.reading.source import DocumentSource
from household_vault.schemas import SCHEMAS

MIN_TEXT_LAYER_CHARS = 20


class PageReader(Protocol):
    def read_pages(
        self, source: DocumentSource, sha256: str, password: str | None
    ) -> list[PageText]: ...


class Models(Protocol):
    @property
    def name(self) -> str: ...

    def classify(self, ocr_text: str, sha256: str) -> str: ...

    def fill(self, doc_type: DocType, images: list[bytes], ocr_text: str, sha256: str) -> str: ...


@dataclass(frozen=True)
class Engines:
    pages: PageReader
    models: Models


def open_image(data: bytes, kind: FileKind) -> Image.Image:
    """An RGB image from photo bytes (HEIC goes through sips first)."""
    if kind is FileKind.heic:
        data = heic_to_png(data)
    try:
        with Image.open(io.BytesIO(data)) as img:
            return img.convert("RGB")
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise DamagedFileError("the photo could not be read") from exc


class VisionPageReader:
    """A PDF page with a text layer is read from it; any other page is rendered and OCRed.
    With `ocr=None` a page without a text layer comes back with no lines."""

    def __init__(self, ocr: OcrEngine | None) -> None:
        self.ocr = ocr

    def _ocr(self, image: Image.Image, page: int) -> PageText:
        lines = self.ocr.read(image, page) if self.ocr else []
        return PageText(page=page, width=image.width, height=image.height, lines=lines)

    def read_pages(
        self, source: DocumentSource, sha256: str, password: str | None
    ) -> list[PageText]:
        if source.kind is FileKind.pdf:
            if source.data is None:
                raise ValueError("a PDF source needs its bytes")
            pages: list[PageText] = []
            for i in range(page_count(source.data, password)):
                width, height, lines = text_layer(source.data, i, password)
                if sum(len(ln.text) for ln in lines) >= MIN_TEXT_LAYER_CHARS:
                    pages.append(PageText(page=i, width=width, height=height, lines=lines))
                else:
                    image = render_page(source.data, i, dpi=200, password=password)
                    pages.append(self._ocr(image, i))
            return pages
        if source.kind is FileKind.audio:
            raise ValueError("audio is not a page")
        files = source.images if source.images is not None else [source.data or b""]
        return [self._ocr(open_image(f, source.kind), i) for i, f in enumerate(files)]


def prefill_for(model: str) -> bool:
    """The thinking builds of qwen3-vl ignore `think: false`; they get an empty think block
    to continue from. The instruct builds and text-only qwen3 do not need it."""
    return model.startswith("qwen3-vl") and "instruct" not in model


class OllamaModels:
    """With the vision tag pulled: the type from OCR text and the fields from page images, both
    by the vision model. Without it, both calls go to the fallback on OCR text."""

    def __init__(self, client: OllamaClient, vision_model: str, fallback_model: str) -> None:
        self.client = client
        self.vision_model = vision_model
        self.fallback_model = fallback_model
        self._vision: bool | None = None

    @property
    def name(self) -> str:
        if self._vision is False:
            return f"ollama:{self.fallback_model} (fallback, {self.vision_model} not pulled)"
        return f"ollama:{self.vision_model}"

    def _has_vision(self) -> bool:
        if self._vision is None:
            tags = self.client.tags()
            if self.vision_model in tags:
                self._vision = True
            elif self.fallback_model in tags:
                self._vision = False
            else:
                raise ModelUnavailable("neither the vision model nor the fallback is pulled")
        return self._vision

    @property
    def _model(self) -> str:
        return self.vision_model if self._has_vision() else self.fallback_model

    def classify(self, ocr_text: str, sha256: str) -> str:
        model = self._model
        return self.client.chat_json(
            model, CLASSIFY_SYSTEM, classify_prompt(ocr_text), [], classify_schema(),
            prefill_for(model),
        )  # fmt: skip

    def fill(self, doc_type: DocType, images: list[bytes], ocr_text: str, sha256: str) -> str:
        model = self._model
        schema = schema_for_prompt(SCHEMAS[doc_type])
        use_images = self._vision is True and bool(images)
        user = user_prompt(doc_type.value, json.dumps(schema), None if use_images else ocr_text)
        return self.client.chat_json(
            model, PROMPT_V2.system, user, images if use_images else [], schema,
            prefill_for(model),
        )  # fmt: skip


class StandInModels:
    """For CI and the Docker image: the type from the page's own title words, no fields."""

    name = "stand-in"

    def classify(self, ocr_text: str, sha256: str) -> str:
        best = best_cue_match(ocr_text)
        return json.dumps({"doc_type": (best or DocType.other).value})

    def fill(self, doc_type: DocType, images: list[bytes], ocr_text: str, sha256: str) -> str:
        return "{}"


def make_engines(settings: Settings) -> Engines:
    if settings.reader == "mac":
        client = OllamaClient(settings.ollama_url)
        return Engines(
            VisionPageReader(AppleVisionOcr()),
            OllamaModels(client, settings.vision_model, settings.fallback_model),
        )
    if settings.reader == "stand-in":
        return Engines(VisionPageReader(None), StandInModels())
    raise ConfigError("the recorded reader is not available yet")
