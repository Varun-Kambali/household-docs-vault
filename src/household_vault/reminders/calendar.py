"""Calendar titles and links. A title carries only the verb, the type label, a warranty part
and the place: never an identifier, an amount, a date of birth or a run of four digits."""

import re
from datetime import timedelta
from typing import TYPE_CHECKING
from urllib.parse import urlencode

from household_vault.db import DocumentRow
from household_vault.reminders.rules import Rule
from household_vault.schemas import SCHEMAS
from household_vault.schemas._coerce import field_kind
from household_vault.search.vocab import PLACE_FIELDS, TYPE_LABELS

if TYPE_CHECKING:
    from household_vault.reminders.compute import Reminder

CALENDAR_URL = "https://calendar.google.com/calendar/render"
MAX_TITLE = 60
_DIGITS = re.compile(r"\d{4,}")  # any script, so Devanagari or Kannada digits go too
_PRIVATE_KINDS = frozenset({"identifier", "aadhaar", "gstin", "amount", "date"})


def _place(doc: DocumentRow) -> str | None:
    schema = SCHEMAS[doc.doc_type]
    for name in PLACE_FIELDS[doc.doc_type]:
        value = doc.fields.get(name)
        if name in schema.model_fields and field_kind(schema, name) in _PRIVATE_KINDS:
            continue
        if isinstance(value, str) and value.strip():
            return value
    return None


def _tidy(text: str) -> str:
    text = _DIGITS.sub("", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"(\s*,)+", ",", text)
    text = re.sub(r",(?=\S)", ", ", text)
    return text.strip(" ,")


def _clip(text: str) -> str:
    if len(text) <= MAX_TITLE:
        return text
    cut = text[:MAX_TITLE]
    if text[MAX_TITLE] != " ":
        cut = cut.rsplit(" ", 1)[0] if " " in cut else cut
    return cut.rstrip(" ,")


def title_of(rule: Rule, doc: DocumentRow, part: str | None) -> str:
    pieces = [f"{rule.verb} {TYPE_LABELS[doc.doc_type]}"]
    if part:
        pieces.append(part)
    place = _place(doc)
    if place:
        pieces.append(place)
    return _clip(_tidy(", ".join(pieces)))


def calendar_link(reminder: "Reminder") -> str | None:
    """An all-day event on the due date, or None when the rule has no calendar entry."""
    if not reminder.calendar:
        return None
    day = reminder.due
    query = urlencode(
        {
            "action": "TEMPLATE",
            "text": reminder.title,
            "dates": f"{day:%Y%m%d}/{day + timedelta(days=1):%Y%m%d}",
        }
    )
    return f"{CALENDAR_URL}?{query}"
