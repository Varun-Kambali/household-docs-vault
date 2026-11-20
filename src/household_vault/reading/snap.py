"""Spelling snap: a filled text value that is not on the page but is a near match to the page's
own OCR text takes the OCR spelling.

The vision model sometimes drops or adds a letter in a name that Apple Vision read correctly
(`SURESHER N RAO` for `SURESH N RAO`). Only name, text and address fields (and the items of a
list of those) are touched; identifiers, dates, amounts and secret fields never are. The
function is pure: the same value and lines always give the same answer.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from difflib import SequenceMatcher
from typing import Any, get_args, get_origin

from pydantic import BaseModel, ValidationError

from household_vault.schemas._coerce import Kind, _markers, _members, field_kind, secret_fields
from household_vault.scoring import edit_distance

SNAP_KINDS = frozenset({"name", "text", "address"})
MIN_RATIO = 0.85
MAX_EDIT_SHARE = 0.15
MIN_EDITS = 2
TIE_MARGIN = 0.02


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip()


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def snap_value(value: str, lines: Sequence[str]) -> str:
    """The value to keep: the OCR spelling of its near match, or the value itself."""
    want = _norm(value)
    if not want or not lines:
        return value
    normed = [_norm(ln) for ln in lines]
    if any(want in n for n in normed) or want in " ".join(normed):
        return value
    count = len(want.split())
    scored: dict[str, tuple[float, str]] = {}  # normalised candidate -> (ratio, OCR spelling)
    for line in lines:
        words = line.split()
        for size in sorted({max(1, count - 1), count, count + 1}):
            for start in range(len(words) - size + 1):
                text = " ".join(words[start : start + size])
                key = _norm(text)
                if key not in scored:
                    scored[key] = (_ratio(want, key), text)
    if not scored:
        return value
    best_key = max(scored, key=lambda k: (scored[k][0], k))
    best, text = scored[best_key]
    if best < MIN_RATIO or edit_distance(want, best_key) > max(
        MIN_EDITS, MAX_EDIT_SHARE * len(want)
    ):
        return value
    if any(k != best_key and r >= best - TIE_MARGIN for k, (r, _) in scored.items()):
        return value
    return text


def _item_kind(schema: type[BaseModel], name: str) -> str | None:
    """The kind of a list field's items when they are plain text, else None."""
    for member in _members(schema.model_fields[name].annotation):
        if get_origin(member) is list:
            for marker in _markers(get_args(member)[0]):
                if isinstance(marker, Kind):
                    return marker.kind
    return None


def _valid(schema: type[BaseModel], name: str, value: Any) -> bool:
    try:
        schema.model_validate({name: value})
    except ValidationError:
        return False
    return True


def snap_fields(
    schema: type[BaseModel], fields: dict[str, Any], lines: Sequence[str]
) -> dict[str, Any]:
    """The fields with each snappable text value (or list item) snapped. A snapped value is
    parsed again by its own field, and kept only when that parse accepts it."""
    secret = secret_fields(schema)
    out = dict(fields)
    for name, value in fields.items():
        if name in secret or name not in schema.model_fields:
            continue
        kind = field_kind(schema, name)
        if kind in SNAP_KINDS and isinstance(value, str):
            snapped: Any = snap_value(value, lines)
        elif kind == "list" and isinstance(value, list) and _item_kind(schema, name) in SNAP_KINDS:
            snapped = [snap_value(v, lines) if isinstance(v, str) else v for v in value]
        else:
            continue
        if snapped != value and _valid(schema, name, snapped):
            out[name] = snapped
    return out
