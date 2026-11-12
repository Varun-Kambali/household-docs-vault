"""Score one extraction against the ground truth, field by field.

A field is correct when the model's value, read through the schema, equals the truth read the
same way: dates by value, amounts by number, lists as sets of items, other text with case,
spacing and commas ignored. Extra keys in the model's JSON are ignored. A missing or null field
is wrong.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError


@dataclass(frozen=True)
class DocScore:
    valid_json: bool  # the output parses as a JSON object
    exact: dict[str, bool]  # one entry per ground-truth field


def _norm(text: str) -> str:
    # Commas go too: a wrapped address prints without them, while the ground truth has them.
    return re.sub(r"\s+", " ", text.replace(",", " ").strip()).casefold()


def _is_list_field(schema: type[BaseModel], key: str) -> bool:
    try:
        schema.model_validate({key: []})
    except ValidationError:
        return False
    return True


def _item_text(item: Any) -> str:
    key = getattr(item, "key", None)
    return _norm(key() if callable(key) else str(item))


def _canon(schema: type[BaseModel], key: str, value: Any) -> object | None:
    """The value as the schema reads it, in a form that compares with ==. None if unreadable."""
    if value is None:
        return None
    for attempt in (value, str(value) if isinstance(value, int | float) else value):
        try:
            parsed = getattr(schema.model_validate({key: attempt}), key)
        except ValidationError:
            continue
        if parsed is None:
            return None
        if isinstance(parsed, list):
            return frozenset(_item_text(i) for i in parsed)
        if isinstance(parsed, str):
            return _norm(parsed)
        return parsed
    return None


def _truth_canon(schema: type[BaseModel], key: str, truth: str) -> object:
    if _is_list_field(schema, key):
        return frozenset(_norm(p) for p in truth.split(";") if p.strip())
    canon = _canon(schema, key, truth)
    return _norm(truth) if canon is None else canon


def score_doc(truth: dict[str, str], got_json: str, schema: type[BaseModel]) -> DocScore:
    try:
        got = json.loads(got_json)
    except (json.JSONDecodeError, TypeError):
        got = None
    if not isinstance(got, dict):
        return DocScore(False, dict.fromkeys(truth, False))
    exact = {}
    for key, expected in truth.items():
        value = _canon(schema, key, got.get(key))
        exact[key] = value is not None and value == _truth_canon(schema, key, expected)
    return DocScore(True, exact)
