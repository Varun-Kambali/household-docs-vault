"""Read a model's JSON into a schema one field at a time, so one bad value does not lose the page.

A field that fails becomes None and gets a short reason in `issues` that never repeats the value.
The code checks the document makes sense (dates in order, no future birth date), and in app mode
that an Aadhaar number or GSTIN passes its checksum.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from household_vault.checks import find_numbers, id_checksum_issue, luhn_valid
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


def mask_card_numbers(text: str, *, any_long_run: bool = False, keep: int = 4) -> str:
    """Replace every digit of each card number except the last `keep` (four) with X, keeping
    separators.

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
        for i in positions[: len(positions) - keep]:
            chars[i] = "X"
    return "".join(chars)


# Up to three non-alphanumeric characters between digit groups: space, tab, dot, slash, hyphen,
# the dashes, the non-breaking hyphen, NBSP, underscore, zero-width space.
_SEP = r"[\s.\-/\u2010-\u2015\u00a0_\u200b-\u200d]{1,3}"
_CANDIDATE = re.compile(rf"\d+(?:{_SEP}\d+)*")
_SHAPES = ((4, 4, 4, 4), (4, 6, 5), (4, 4, 4, 4, 3))


def mask_card_shapes(text: str) -> str:
    """For a card's letter or statement: mask (all digits but the last four) every run of digit
    groups that has a card shape (4-4-4-4, 4-6-5, 4-4-4-4-3) or passes Luhn at 13 to 19 digits,
    whatever separators sit between the groups, and any single group of 13 digits or more.
    Dates and amount rows are not shaped like that, so they stay readable."""
    spans: list[list[int]] = []  # start, end, 1 when no digit may stay (a run that holds a CVV)
    for cand in _CANDIDATE.finditer(text):
        groups = [
            (cand.start() + g.start(), cand.start() + g.end())
            for g in re.finditer(r"\d+", cand.group())
        ]
        for i in range(len(groups)):
            total = 0
            lengths: list[int] = []
            for j in range(i, len(groups)):
                size = groups[j][1] - groups[j][0]
                total += size
                lengths.append(size)
                if total > 19 and j > i:
                    break
                shaped = 13 <= total <= 19 and tuple(lengths) in _SHAPES
                loose = (
                    13 <= total <= 19
                    and len(lengths) >= 3
                    and min(lengths) >= 3
                    and max(lengths) >= 4  # an amount row of 3-digit groups stays
                )
                hit = (
                    (j == i and size >= 13)
                    or shaped
                    or loose
                    or (
                        13 <= total <= 19
                        and min(lengths) >= 3  # a date or an amount row has short groups
                        and luhn_valid(
                            "".join(c for c in text[groups[i][0] : groups[j][1]] if c.isdigit())
                        )
                    )
                )
                if hit:
                    none = int(loose and not shaped and total > 16)
                    span = [groups[i][0], groups[j][1], none]
                    if spans and span[0] < spans[-1][1]:
                        spans[-1][1] = max(spans[-1][1], span[1])
                        spans[-1][2] |= none
                    else:
                        spans.append(span)
    chars = list(text)
    for start, end, none in spans:
        positions = [i for i in range(start, end) if chars[i].isdigit()]
        for i in positions[: len(positions) - (0 if none else 4)]:
            chars[i] = "X"
    return "".join(chars)


_GLUED = re.compile(r"\d+(?:[ -]\d+)*")


def mask_glued_runs(text: str, number: str | None, *, keep_none_over: int = 19) -> str:
    """A card number glued to other digits (its CVV, another number): every digit of such a run
    goes except the last four of the number that was read. With no number read, a run of more
    than 19 digits loses all of its digits."""
    chars = list(text)
    for m in _GLUED.finditer(text):
        positions = [i for i in range(m.start(), m.end()) if chars[i].isdigit()]
        digits = "".join(chars[i] for i in positions)
        if number and number in digits and len(digits) > len(number):
            at = digits.index(number) + len(number)
            keep = set(positions[at - 4 : at])
        elif len(digits) > keep_none_over:
            keep = set()
        else:
            continue
        for i in positions:
            if i not in keep:
                chars[i] = "X"
    return "".join(chars)
