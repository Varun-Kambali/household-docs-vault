"""Score extracted fields against the ground truth, field by field.

A field is right when the value read through the schema equals the truth read the same way:
dates and amounts by value, lists as multisets of item keys, text by its kind's normaliser.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from household_vault.fieldkinds import FieldKind
from household_vault.schemas._coerce import field_kind, parse_amount, parse_date


def normalise(kind: FieldKind, text: str) -> str:
    """The comparison form of text for a field kind."""
    folded = text.casefold()
    if kind in ("identifier", "aadhaar", "gstin"):
        return re.sub(r"[\s-]", "", folded)
    if kind == "address":
        return re.sub(r"\s+", " ", folded.replace(",", " ")).strip()
    if kind == "name":
        return re.sub(r"\s+", " ", folded.replace(".", "")).strip()
    return re.sub(r"\s+", " ", folded).strip()


@dataclass(frozen=True)
class FieldScore:
    exact: dict[str, bool]  # one entry per truth field that is not None
    tp: int
    fp: int
    fn: int


def _item_key(item: Any) -> str:
    key = getattr(item, "key", None)
    return normalise("text", key() if callable(key) else str(item))


def _truth_items(truth: Any) -> list[str]:
    if isinstance(truth, str):
        return [p for p in truth.split(";") if p.strip()]
    return [str(t) for t in truth]


def _same(kind: FieldKind, truth: Any, got: Any) -> bool:
    try:
        if kind == "date":
            return bool(parse_date(truth) == got)
        if kind == "amount":
            return bool(parse_amount(truth) == got)
    except ValueError:
        return False
    if kind == "list":
        want = Counter(normalise("text", t) for t in _truth_items(truth))
        return want == Counter(_item_key(i) for i in got)
    return normalise(kind, str(truth)) == normalise(kind, str(got))


def score_fields(schema: type[BaseModel], truth: Mapping[str, Any], got: BaseModel) -> FieldScore:
    exact: dict[str, bool] = {}
    tp = fp = fn = 0
    for name in schema.model_fields:
        expected, value = truth.get(name), getattr(got, name, None)
        if expected is None:
            if value is not None:
                fp += 1
            continue
        right = value is not None and _same(field_kind(schema, name), expected, value)
        exact[name] = right
        if right:
            tp += 1
        else:
            fn += 1
            if value is not None:
                fp += 1
    return FieldScore(exact, tp, fp, fn)
