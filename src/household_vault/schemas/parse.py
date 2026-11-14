"""Read a model's JSON into a schema one field at a time, so one bad value does not lose the page.

A field that fails becomes None and gets a short reason in `issues` that never repeats the value.
The code checks the document makes sense (dates in order, no future birth date), and in app mode
that an Aadhaar number or GSTIN passes its checksum.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from household_vault.checks import find_numbers, id_checksum_issue
from household_vault.schemas._coerce import field_kind

Mode = Literal["dev", "app"]

# (end field, start field) pairs; an end earlier than its start is dropped.
_ORDERED_DATES = (
    ("end_date", "start_date"),
    ("expiry_date", "issue_date"),
    ("period_end", "period_start"),
)


@dataclass(frozen=True)
class ParsedFields:
    model: BaseModel
    issues: dict[str, str]


def _reason(err: ValidationError) -> str:
    """A short reason from the first error. Parser messages never contain the value."""
    first = err.errors(include_input=False, include_url=False, include_context=False)[0]
    msg = str(first["msg"])
    if first["type"] == "value_error":
        return msg.removeprefix("Value error, ")
    return "wrong kind of value"


def parse_fields(schema: type[BaseModel], raw: Any, *, mode: Mode) -> ParsedFields:
    if not isinstance(raw, dict):
        return ParsedFields(schema.model_validate({}), {"_json": "not a JSON object"})
    good: dict[str, Any] = {}
    issues: dict[str, str] = {}
    for name in schema.model_fields:
        if name not in raw:
            continue
        value = raw[name]
        if field_kind(schema, name) == "list" and isinstance(value, list):
            kept = []
            for i, item in enumerate(value):
                try:
                    schema.model_validate({name: [item]})
                except ValidationError as err:
                    issues[f"{name}[{i}]"] = _reason(err)
                else:
                    kept.append(item)
            if kept or not value:
                good[name] = kept
            continue
        try:
            schema.model_validate({name: value})
        except ValidationError as err:
            issues[name] = _reason(err)
        else:
            good[name] = value
    model = schema.model_validate(good)
    drop: dict[str, str] = {}
    for end, start in _ORDERED_DATES:
        e, s = getattr(model, end, None), getattr(model, start, None)
        if isinstance(e, date) and isinstance(s, date) and e < s:
            drop[end] = "ends before it starts"
    born = getattr(model, "date_of_birth", None)
    if isinstance(born, date) and born > date.today():
        drop["date_of_birth"] = "in the future"
    for name in schema.model_fields:
        kind = field_kind(schema, name)
        value = getattr(model, name)
        if kind in ("aadhaar", "gstin") and isinstance(value, str) and name not in drop:
            problem = id_checksum_issue(kind, value, mode=mode)
            if problem:
                drop[name] = problem
    if drop:
        model = model.model_copy(update=dict.fromkeys(drop))
        issues.update(drop)
    return ParsedFields(model, issues)


def parse_json_fields(schema: type[BaseModel], text: str, *, mode: Mode) -> ParsedFields:
    try:
        raw = json.loads(text)
    except (json.JSONDecodeError, TypeError, RecursionError):
        return ParsedFields(schema.model_validate({}), {"_json": "not valid JSON"})
    return parse_fields(schema, raw, mode=mode)


def mask_card_numbers(text: str, *, any_long_run: bool = False) -> str:
    """Replace every digit of each card number except the last four with X, keeping separators.

    The only mask style in the app. Overlapping hits are merged first, so no window leaves a
    different set of digits showing.
    """
    spans: list[list[int]] = []
    for hit in find_numbers(text, allow_test_cards=False, any_long_run=any_long_run):
        if hit.kind != "card":
            continue
        if spans and hit.start < spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], hit.end)
        else:
            spans.append([hit.start, hit.end])
    chars = list(text)
    for start, end in spans:
        positions = [i for i in range(start, end) if chars[i].isdigit()]
        for i in positions[:-4]:
            chars[i] = "X"
    return "".join(chars)
