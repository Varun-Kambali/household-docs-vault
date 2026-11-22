"""The sentence under a search: what is shown, for whom, which date and where, with a menu on
each part. Changing a part builds a new query in code, so no model is involved."""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Literal

from pydantic import JsonValue

from household_vault.doctypes import Area, DocType
from household_vault.people import Household
from household_vault.search.answer import format_date
from household_vault.search.dates import DateRange, add_months, parse_date_phrase
from household_vault.search.query import Query
from household_vault.search.vocab import AREA_LABELS, TYPE_LABELS, DateRole

Slot = Literal["what", "who", "verb", "when", "place"]

VERBS: dict[DateRole, str] = {
    "expiry": "expire",
    "renewal": "renew",
    "due": "fall due",
    "purchase": "were bought",
    "issue": "were issued",
    "document": "are dated",
}
_PRESETS = {
    "next_30": ("next 30 days", "next 30 days"),
    "next_60": ("next 60 days", "next 60 days"),
    "this_month": ("this month", "this month"),
    "this_year": ("this year", "this year"),
}


@dataclass(frozen=True)
class Option:
    value: JsonValue
    label: str


@dataclass(frozen=True)
class Part:
    slot: Slot
    text: str
    value: JsonValue
    options: list[Option] = field(default_factory=list)


@dataclass(frozen=True)
class Sentence:
    parts: list[Part]


def _plural(label: str) -> str:
    if label.endswith("y") and not label.endswith(("ay", "ey", "oy", "uy")):
        return label[:-1] + "ies"
    return label + "s"


def _joined(names: list[str]) -> str:
    if len(names) <= 2:
        return " and ".join(names)
    return ", ".join(names[:-1]) + f" and {names[-1]}"


def _what(query: Query) -> str:
    if query.types:
        return _joined([_plural(TYPE_LABELS[t]) for t in query.types])
    if query.areas:
        return _joined([f"{AREA_LABELS[a]} documents" for a in query.areas])
    return "documents"


def _who(query: Query, household: Household) -> str:
    if not query.people:
        return "everyone"
    known = {p.id: p.name for p in household.people}
    return _joined([known.get(p, "the household" if p == "home" else p) for p in query.people])


def _when(span: DateRange | None) -> str:
    if span is None or (span.start is None and span.end is None):
        return "any time"
    if span.start is not None and span.end is not None:
        if span.start == span.end:
            return f"on {format_date(span.start)}"
        return f"between {format_date(span.start)} and {format_date(span.end)}"
    if span.end is not None:
        return f"by {format_date(span.end)}"
    assert span.start is not None
    return f"from {format_date(span.start)}"


def _range_value(span: DateRange | None) -> JsonValue:
    if span is None:
        return None
    return {
        "start": span.start.isoformat() if span.start else None,
        "end": span.end.isoformat() if span.end else None,
    }


def _what_options() -> list[Option]:
    return [
        Option("all", "all documents"),
        *(Option(f"area:{a.value}", AREA_LABELS[a]) for a in Area),
        *(Option(f"type:{t.value}", TYPE_LABELS[t]) for t in DocType),
    ]


def _when_options(today: date) -> list[Option]:
    options = [Option("any", "any time")]
    options += [Option(key, label) for key, (label, _) in _PRESETS.items()]
    first = today.replace(day=1)
    for ahead in range(1, 7):
        month = add_months(first, ahead)
        options.append(Option(f"before:{month.isoformat()}", f"before {format_date(month)}"))
    options.append(Option("custom", "a custom range"))
    return options


def sentence(query: Query, household: Household, today: date) -> Sentence:
    role: DateRole = query.role or "document"
    parts = [
        Part("what", _what(query), None, _what_options()),
        Part(
            "who",
            _who(query, household),
            list(query.people),
            [Option([], "everyone"), *(Option(p.id, p.name) for p in household.people)],
        ),
        Part("verb", VERBS[role], role, [Option(r, v) for r, v in VERBS.items()]),
        Part("when", _when(query.range), _range_value(query.range), _when_options(today)),
    ]
    if query.place:
        parts.append(Part("place", query.place, query.place, []))
    return Sentence(parts)


def render(s: Sentence) -> str:
    said = {p.slot: p.text for p in s.parts}
    text = f"Showing {said['what']} for {said['who']} that {said['verb']} {said['when']}"
    return text + (f" from {said['place']}" if "place" in said else "")


def _iso(value: object) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError("not a date") from exc


def _span(value: JsonValue, today: date) -> DateRange | None:
    if isinstance(value, dict):
        return DateRange(start=_iso(value.get("start")), end=_iso(value.get("end")))
    if value == "any":
        return None
    if isinstance(value, str) and value in _PRESETS:
        span = parse_date_phrase(_PRESETS[value][1], today)
        if span is not None:
            return span
    if isinstance(value, str) and value.startswith("before:"):
        first = _iso(value.removeprefix("before:"))
        if first is not None:
            return DateRange(end=first - timedelta(days=1))
    raise ValueError("not a way to change the dates")


def apply_part(query: Query, slot: str, value: JsonValue, today: date) -> Query:
    """The query a dropdown change makes. Raises ValueError for a slot or value it does not
    offer."""
    if slot == "who":
        ids = [value] if isinstance(value, str) else value
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
            raise ValueError("not a person")
        return query.model_copy(update={"people": [str(i) for i in ids]})
    if slot == "what":
        if value == "all":
            return query.model_copy(update={"types": [], "areas": []})
        if isinstance(value, str) and value.startswith("area:"):
            return query.model_copy(
                update={"types": [], "areas": [Area(value.removeprefix("area:"))]}
            )
        if isinstance(value, str) and value.startswith("type:"):
            return query.model_copy(
                update={"types": [DocType(value.removeprefix("type:"))], "areas": []}
            )
        raise ValueError("not a kind of document")
    if slot == "verb":
        if isinstance(value, str) and value in VERBS:
            role: DateRole = value
            return query.model_copy(update={"role": role})
        raise ValueError("not a verb")
    if slot == "when":
        if value == "custom":
            return query  # the screen asks for the two dates, then sends them
        return query.model_copy(update={"range": _span(value, today)})
    if slot == "place":
        if value is not None and not isinstance(value, str):
            raise ValueError("not a place")
        return query.model_copy(update={"place": value or None})
    raise ValueError("no such part")
