"""Read one document: pages to text, the type, then the fields.

Only the fill call, the card-reading step, ever sees a full card number. The type call gets text
with every 13 to 19 digit run masked, the stored lines are masked, and secret fields' values sit
in `secret_values`, which no dump, repr, log or recording carries.
"""

from __future__ import annotations

import json
import time
from typing import Any, Literal

from pydantic import BaseModel, Field, JsonValue

from household_vault.doctypes import DocType
from household_vault.intake.sniff import FileKind
from household_vault.reading.cues import CueCheck, cue_check
from household_vault.reading.engines import Engines
from household_vault.reading.heic import heic_to_png
from household_vault.reading.lines import Line, PageText
from household_vault.reading.ollama import ModelError
from household_vault.reading.prompt import OCR_TEXT_LIMIT, PROMPT_V2, ocr_to_text
from household_vault.reading.render import page_count, png_bytes, render_page
from household_vault.reading.source import DocumentSource
from household_vault.schemas import SCHEMAS
from household_vault.schemas._coerce import secret_fields
from household_vault.schemas.parse import mask_card_numbers, parse_json_fields

MAX_VISION_PAGES = 2
MIN_ENGLISH_LETTERS = 40

__all__ = [
    "MAX_VISION_PAGES",
    "MIN_ENGLISH_LETTERS",
    "OCR_TEXT_LIMIT",
    "Reading",
    "read_document",
]


class Reading(BaseModel):
    pages: list[PageText]
    english_letters: int
    doc_type: DocType | None = None
    type_check: CueCheck | None = None
    fields: dict[str, JsonValue] = Field(default_factory=dict)
    issues: dict[str, str] = Field(default_factory=dict)
    seconds: dict[str, float] = Field(default_factory=dict)
    engine: str = ""
    prompt_version: str = PROMPT_V2.version
    vision_pages: int = 0
    # Left out of every dump and repr: card numbers and the models' raw answers.
    secret_values: dict[str, str] = Field(default_factory=dict, exclude=True, repr=False)
    raw: dict[str, str] = Field(default_factory=dict, exclude=True, repr=False)


def _english_letters(pages: list[PageText]) -> int:
    return sum(
        1
        for p in pages
        for ln in p.lines
        if ln.lang == "en"
        for c in ln.text
        if c.isascii() and c.isalpha()
    )


# Types whose pages carry a full card number, which may have a misread digit.
_CARD_TYPES = frozenset({DocType.card_front})


def _masked(pages: list[PageText], *, any_long_run: bool) -> list[PageText]:
    """The pages as kept: every line with card numbers masked. Without a type, or for a card,
    every 13 to 19 digit run goes (a misread digit fails Luhn); other types keep non-card
    numbers readable for search."""
    return [
        p.model_copy(
            update={
                "lines": [
                    Line(
                        **{
                            **ln.model_dump(),
                            "text": mask_card_numbers(ln.text, any_long_run=any_long_run),
                        }
                    )
                    for ln in p.lines
                ]
            }
        )
        for p in pages
    ]


def _fill_images(source: DocumentSource, password: str | None) -> list[bytes]:
    """The first MAX_VISION_PAGES page images: photos as their own bytes (HEIC as PNG), PDF
    pages as PNG at 200 dpi."""
    if source.kind is FileKind.pdf:
        data = source.data or b""
        count = min(page_count(data, password), MAX_VISION_PAGES)
        return [png_bytes(render_page(data, i, dpi=200, password=password)) for i in range(count)]
    files = source.images if source.images is not None else [source.data or b""]
    return list(files[:MAX_VISION_PAGES])


def _classify(engines: Engines, text: str, sha256: str, raw: dict[str, str]) -> DocType | None:
    """The model's answer, retried once when it is broken or names an unknown type (then
    other). None when the model itself failed on the second try."""
    failed = False
    for _ in range(2):
        try:
            answer = engines.models.classify(text, sha256)
        except ModelError:
            failed = True
            continue
        failed = False
        raw["classify"] = answer
        try:
            value = json.loads(answer)["doc_type"]
            doc_type = DocType(value)
        except (ValueError, KeyError, TypeError):
            continue
        if doc_type is not DocType.visit_recording:
            return doc_type
    return None if failed else DocType.other


def read_document(
    source: DocumentSource,
    sha256: str,
    engines: Engines,
    *,
    mode: Literal["dev", "app"],
    password: str | None = None,
    forced_type: DocType | None = None,
) -> Reading:
    if forced_type is DocType.visit_recording:
        raise ValueError("a recording is not read as a page")
    if source.kind is FileKind.heic:  # converted once; the page reader and the fill share it
        files = source.images if source.images is not None else [source.data or b""]
        converted = [heic_to_png(f) for f in files]
        source = DocumentSource(
            FileKind.png,
            data=None if source.images is not None else converted[0],
            images=converted if source.images is not None else None,
        )
    started = time.perf_counter()
    pages = engines.pages.read_pages(source, sha256, password)
    read_seconds = round(time.perf_counter() - started, 3)
    letters = _english_letters(pages)
    reading = Reading(
        pages=_masked(pages, any_long_run=True),
        english_letters=letters,
        seconds={"read": read_seconds},
        engine=engines.models.name,
        prompt_version=PROMPT_V2.version,
    )
    if forced_type is None and letters < MIN_ENGLISH_LETTERS:
        return reading

    doc_type: DocType
    if forced_type is not None:
        doc_type = forced_type
    else:
        started = time.perf_counter()
        text = mask_card_numbers(
            ocr_to_text([ln for p in pages for ln in p.lines]), any_long_run=True
        )
        classified = _classify(engines, text, sha256, reading.raw)
        reading.seconds["classify"] = round(time.perf_counter() - started, 3)
        if classified is None:
            reading.issues = {"_json": "the type could not be read"}
            return reading
        doc_type = classified
        reading.type_check = cue_check(text, doc_type)
    reading.doc_type = doc_type
    if doc_type not in _CARD_TYPES:
        reading.pages = _masked(pages, any_long_run=False)
    reading.engine = engines.models.name  # a fallback shows once the models have been asked
    if doc_type is DocType.other:
        return reading

    schema = SCHEMAS[doc_type]
    started = time.perf_counter()
    images = _fill_images(source, password)
    reading.vision_pages = len(images)
    fill_text = ocr_to_text([ln for p in pages[:MAX_VISION_PAGES] for ln in p.lines])
    parsed = None
    for _ in range(2):
        try:
            answer = engines.models.fill(doc_type, images, fill_text, sha256)
        except ModelError:
            continue
        reading.raw["fill"] = answer
        attempt = parse_json_fields(schema, answer, mode=mode)
        if "_json" not in attempt.issues:
            parsed = attempt
            break
    reading.seconds["fill"] = round(time.perf_counter() - started, 3)
    if parsed is None:
        reading.fields = dict.fromkeys(schema.model_fields)
        reading.issues = {"_json": "the model did not return usable JSON"}
        return reading
    dumped: dict[str, Any] = parsed.model.model_dump(mode="json")
    for name in secret_fields(schema):
        value = dumped.get(name)
        if value is not None:
            reading.secret_values[name] = str(value)
        dumped[name] = None
    reading.fields = dumped
    reading.issues = parsed.issues
    return reading
