"""Recordings of what the page reader and the models answered for one document, and engines that
replay them. The eval runs the real models once, records, and every later run (the filing eval,
the CI smoke run) replays the recording with no model.

Development only. A recording holds the page lines and the model's raw answers, so it can hold a
card number: before anything is written, every card-number-shaped run that is not one of the
networks' published test numbers is masked, and writing is refused in app mode.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from household_vault.checks import find_numbers
from household_vault.doctypes import DocType
from household_vault.reading.engines import Engines
from household_vault.reading.lines import Line, PageText
from household_vault.reading.ollama import ModelError, ModelUnavailable
from household_vault.reading.source import DocumentSource
from household_vault.safety import assert_safe_path

_KEY = re.compile(r"[0-9a-f]{64}")


class RecordingRefused(Exception):
    """A recording was asked for where recordings are not allowed."""


class Recording(BaseModel):
    """One document as the reader saw it. `key` is `document_key` of its files."""

    key: str
    doc_id: str
    pages: list[PageText]
    classify_raw: str | None
    fill_raw: str | None
    seconds: dict[str, float]
    engine: str
    prompt_version: str


def _path(folder: Path, key: str) -> Path:
    if not _KEY.fullmatch(key):
        raise ValueError("a recording key is a SHA-256 in lowercase hex")
    return folder / f"{key}.json"


def mask_untested_numbers(text: str) -> str:
    """Every digit but the last four of each card-shaped run (13 to 19 digits, Luhn or not)
    becomes X, except the published test numbers, which stay so replays can score them."""
    spans: list[list[int]] = []
    for hit in find_numbers(text, allow_test_cards=True, any_long_run=True):
        if hit.kind != "card":
            continue
        if spans and hit.start < spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], hit.end)
        else:
            spans.append([hit.start, hit.end])
    chars = list(text)
    for start, end in spans:
        digits = [i for i in range(start, end) if chars[i].isdigit()]
        for i in digits[:-4]:
            chars[i] = "X"
    return "".join(chars)


def _masked(rec: Recording) -> Recording:
    pages = [
        p.model_copy(
            update={
                "lines": [
                    Line(**{**ln.model_dump(), "text": mask_untested_numbers(ln.text)})
                    for ln in p.lines
                ]
            }
        )
        for p in rec.pages
    ]
    return rec.model_copy(
        update={
            "pages": pages,
            "classify_raw": None
            if rec.classify_raw is None
            else mask_untested_numbers(rec.classify_raw),
            "fill_raw": None if rec.fill_raw is None else mask_untested_numbers(rec.fill_raw),
        }
    )


def write_recording(folder: Path, rec: Recording, *, mode: Literal["dev", "app"] = "dev") -> None:
    """Write the recording as `<key>.json`, with untested card numbers masked."""
    if mode != "dev":
        raise RecordingRefused("recordings are written only in development mode")
    folder = assert_safe_path(folder.expanduser().absolute())
    target = _path(folder, rec.key)
    folder.mkdir(parents=True, exist_ok=True)
    text = _masked(rec).model_dump_json(indent=1) + "\n"
    temp = target.with_name(f".{target.name}.tmp")
    temp.write_text(text, encoding="utf-8")
    os.replace(temp, target)


class _Store:
    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self._cache: dict[str, Recording] = {}

    def get(self, key: str) -> Recording:
        found = self._cache.get(key)
        if found is None:
            try:
                path = _path(self.folder, key)
                found = Recording.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                raise ModelUnavailable("no recording") from None
            self._cache[key] = found
        return found

    def has(self, key: str) -> bool:
        try:
            self.get(key)
        except ModelUnavailable:
            return False
        return True


class RecordedPages:
    """Page reader that returns the recorded pages of the document with this key."""

    def __init__(self, store: _Store) -> None:
        self._store = store

    def read_pages(
        self, source: DocumentSource, sha256: str, password: str | None
    ) -> list[PageText]:
        return [p.model_copy(deep=True) for p in self._store.get(sha256).pages]


class RecordedModels:
    """Models that return the recorded raw answers. An answer the recording does not hold (the
    model failed on that call) fails the same way on replay."""

    def __init__(self, store: _Store) -> None:
        self._store = store

    @property
    def name(self) -> str:
        return "recorded"

    def classify(self, ocr_text: str, sha256: str) -> str:
        answer = self._store.get(sha256).classify_raw
        if answer is None:
            raise ModelError("no answer was recorded for the type")
        return answer

    def fill(self, doc_type: DocType, images: list[bytes], ocr_text: str, sha256: str) -> str:
        answer = self._store.get(sha256).fill_raw
        if answer is None:
            raise ModelError("no answer was recorded for the fields")
        return answer

    def recording(self, key: str) -> Recording:
        return self._store.get(key)


def recorded_engines(folder: Path) -> Engines:
    """Engines that replay the recordings in folder. A key with no recording raises
    `ModelUnavailable("no recording")`."""
    store = _Store(folder)
    return Engines(RecordedPages(store), RecordedModels(store))


def recorded_seconds(engines: Engines, key: str) -> Mapping[str, float] | None:
    """The seconds the original run took, when engines replay recordings; else None."""
    models = engines.models
    if isinstance(models, RecordedModels):
        return models.recording(key).seconds
    return None
