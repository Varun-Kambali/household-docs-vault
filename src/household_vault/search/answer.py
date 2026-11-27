"""Answers composed by code from a document's stored fields.

No model writes any part of an answer. A value is shown only when a line on the page prints it
(`locate`); otherwise the app says there is no direct answer and lists the closest files. A
date or amount a person reads is formatted here, with a fixed month table so the words do not
depend on the Mac's locale.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from difflib import SequenceMatcher
from typing import Any, Literal

from pydantic import JsonValue

from household_vault.db import DocumentRow, Store, StoredLine
from household_vault.doctypes import DocType
from household_vault.fieldkinds import FieldKind
from household_vault.people import normalise_name
from household_vault.schemas import SCHEMAS
from household_vault.schemas._coerce import field_kind, parse_amount, parse_date
from household_vault.search.dates import add_months
from household_vault.search.query import Query
from household_vault.search.retrieve import LineRef, Row
from household_vault.search.vocab import DATE_ROLES, MASKED_FIELDS, field_for

# A top row with no filter behind it is declined when its fused score is under MIN_FUSED (a
# reciprocal-rank score; one ranking's first place scores about 0.016, so this wants two
# rankings to agree) and fewer than MIN_KEYWORD of its lines matched the words. A query with
# residual words (a product, a brand) is declined when no row matches them: no keyword hit on
# the words and no vector score of MIN_VECTOR or more. Tuned on val.
MIN_FUSED = 0.02
MIN_KEYWORD = 1
MIN_VECTOR = 0.62

NEAR_SPELLING = 0.85

# The types whose expiry date answers "is it still valid". The search eval judges the same set.
STATUS_TYPES = frozenset(
    {
        DocType.life_policy,
        DocType.health_policy,
        DocType.vehicle_policy,
        DocType.home_policy,
        DocType.travel_policy,
        DocType.gadget_policy,
        DocType.accident_policy,
        DocType.passport,
        DocType.driving_licence,
        DocType.puc_certificate,
        DocType.rent_agreement,
        DocType.extended_warranty,
        DocType.amc,
    }
)

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


@dataclass(frozen=True)
class Answer:
    text: str
    field: str  # the stored field's name
    value: JsonValue  # the stored value
    document_id: str
    page: int
    lines: list[LineRef]
    masked: bool


@dataclass(frozen=True)
class NoAnswer:
    reason: Literal["no_documents", "unknown_person", "weak_match", "no_field", "not_on_page"]
    closest: list[str]  # paths of the closest files


# -- formatting --------------------------------------------------------------------------------


def format_date(day: date) -> str:
    return f"{day.day} {_MONTHS[day.month - 1]} {day.year}"


def _indian(digits: str) -> str:
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    groups = []
    while len(head) > 2:
        groups.append(head[-2:])
        head = head[:-2]
    return (
        ",".join([head, *reversed(groups), tail]) if head else ",".join([*reversed(groups), tail])
    )


def format_amount(amount: Decimal) -> str:
    """Rupees with Indian grouping; paise only when there are some."""
    text = f"{amount.quantize(Decimal('0.01'), ROUND_HALF_UP):f}"
    whole, paise = text.split(".")
    return f"Rs {_indian(whole)}" + ("" if paise == "00" else f".{paise}")


def _as_date(value: object) -> date | None:
    try:
        return parse_date(value)
    except ValueError:
        return None


def _as_amount(value: object) -> Decimal | None:
    try:
        return parse_amount(value if isinstance(value, str) else Decimal(str(value)))
    except (ValueError, InvalidOperation):
        return None


# -- locating the supporting line --------------------------------------------------------------

_MONTH_WORD = r"[A-Za-z]{3,9}"
_DATE_TOKENS = re.compile(
    r"(?<!\d)(?:"
    r"\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}"
    rf"|\d{{1,2}}(?:st|nd|rd|th)?[ \-]{_MONTH_WORD}[ \-,]+\d{{4}}"
    rf"|{_MONTH_WORD} \d{{1,2}}(?:st|nd|rd|th)?, \d{{4}}"
    r")(?!\d)"
)
# A whole number token: not joined to a letter, digit, "/", "-" or a date's dot on either side
# ("/-" after the number is the rupee form).
_AMOUNT_TOKENS = re.compile(
    r"(?<![\w/\-,])(?<!\d\.)"
    r"\d+(?:,\d+)*(?:\.\d+)?"
    r"(?:\s*(?:lakhs?|lacs?|crores?|cr)(?!\w))?"
    r"(?!\w)(?![/.\-]\d)(?!/(?!-))",
    re.IGNORECASE,
)
_MASK_CHARS = str.maketrans({"*": "x", "\u2022": "x", "\u25cf": "x"})


def _alnum_runs(text: str) -> tuple[str, list[bool], list[bool]]:
    """The letters and digits of a line, case-folded (mask marks read as x), with, for each,
    whether it starts a run (nothing alphanumeric right before it) and whether it ends one."""
    chars: list[str] = []
    starts: list[bool] = []
    ends: list[bool] = []
    after_gap = True
    for raw in text.translate(_MASK_CHARS).casefold():
        if raw.isascii() and raw.isalnum():
            if ends:
                ends[-1] = after_gap
            chars.append(raw)
            starts.append(after_gap)
            ends.append(True)
            after_gap = False
        else:
            after_gap = True
    return "".join(chars), starts, ends


def _alnum(text: str) -> str:
    return _alnum_runs(text)[0]


def _prints_date(want: date, text: str) -> bool:
    return any(_as_date(m.group(0).strip()) == want for m in _DATE_TOKENS.finditer(text))


def _prints_amount(want: Decimal, text: str) -> bool:
    text = _DATE_TOKENS.sub(" ", text)  # a piece of a date is not an amount
    for m in _AMOUNT_TOKENS.finditer(text):
        if (got := _as_amount(m.group(0).strip())) is not None and got == want:
            return True
    return False


def _prints_identifier(want: str, text: str) -> bool:
    """Letters and digits only, case-folded, over a span that starts and ends where a run of
    letters and digits does (so 12345 is not inside 9812345000). A masked line (Xs in front of
    the end of the number) also matches on the same boundaries when its length and last four
    agree and every other position is a mask or the right character."""
    target = _alnum(want)
    line, starts, ends = _alnum_runs(text)
    if not target:
        return False
    size = len(target)
    for end in range(size, len(line) + 1):
        first = end - size
        if not (starts[first] and ends[end - 1]):
            continue
        window = line[first:end]
        if window == target:
            return True
        if size > 4 and window[-4:] == target[-4:]:
            head = zip(window[:-4], target[:-4], strict=True)
            if all(a == "x" or a == b for a, b in head) and window[:-4].count("x") >= 2:
                return True
    return False


def _prints_words(want: str, text: str) -> bool:
    """The words in a row, or a spelling within `NEAR_SPELLING` of the line or of a stretch of
    it as long as the value."""
    target, line = normalise_name(want), normalise_name(text)
    if not target or not line:
        return False
    if f" {target} " in f" {line} ":
        return True
    if SequenceMatcher(None, target, line).ratio() >= NEAR_SPELLING:
        return True
    words, count = line.split(), len(target.split())
    return any(
        SequenceMatcher(None, target, " ".join(words[i : i + count])).ratio() >= NEAR_SPELLING
        for i in range(max(len(words) - count + 1, 1))
    )


def _item_text(item: object) -> str | None:
    """The words that identify a list item: itself, or a part's name."""
    if isinstance(item, dict):
        name = item.get("part")
        return (
            name
            if isinstance(name, str)
            else next((v for v in item.values() if isinstance(v, str)), None)
        )
    return item if isinstance(item, str) else None


def _prints(value: object, kind: FieldKind, text: str) -> bool:
    if kind == "date":
        day = _as_date(value)
        return day is not None and _prints_date(day, text)
    if kind == "amount":
        amount = _as_amount(value)
        return amount is not None and _prints_amount(amount, text)
    if kind in ("identifier", "aadhaar", "gstin"):
        return _prints_identifier(str(value), text)
    return _prints_words(str(value), text)


def _item_prints(item: object, text: str) -> bool:
    if isinstance(item, bool):
        return False
    if isinstance(item, int | float | Decimal):
        return _prints(item, "amount", text)
    words = _item_text(item)
    return words is not None and _prints_words(words, text)


def locate(value: JsonValue, kind: FieldKind, lines: Sequence[StoredLine]) -> list[LineRef]:
    """The lines that print the value, as each kind reads it. A list is located item by item
    and gives the lines of every item that is found."""
    if value is None or value == "" or value == []:
        return []
    out: list[LineRef] = []
    for ln in lines:
        if kind == "list":
            items = value if isinstance(value, list) else [value]
            found = any(_item_prints(item, ln.text) for item in items)
        else:
            found = _prints(value, kind, ln.text)
        if found:
            out.append(LineRef(ln.page, ln.idx, ln.bbox))
    return out


# -- composing ---------------------------------------------------------------------------------


def _filtered(query: Query) -> bool:
    return bool(
        query.people or query.types or query.areas or query.place or query.range is not None
    )


def _ends(end: date, today: date) -> str:
    return f"yes, until {format_date(end)}" if end >= today else f"ended {format_date(end)}"


def _part_end(start: date, years: Decimal) -> date:
    """The last covered day: the purchase date plus the part's years, less one day, the way
    the policies print their ends. A fraction counts as whole months; an anniversary on 29 Feb
    falls on 28 Feb in a year without one."""
    months = int((years * 12).to_integral_value(ROUND_HALF_UP))
    return add_months(start, months) - timedelta(days=1)


def _warranty_text(doc: DocumentRow, today: date) -> str | None:
    start = _as_date(doc.fields.get("purchase_date"))
    parts = doc.fields.get("warranty_parts")
    if start is None or not isinstance(parts, list):
        return None
    said = []
    for item in parts:
        if not isinstance(item, dict) or not isinstance(item.get("part"), str):
            continue
        years = _as_amount(item.get("years"))
        if years is None:
            continue
        said.append(f"{item['part']}: {_ends(_part_end(start, years), today)}.")
    return " ".join(said) or None


def _list_text(items: list[Any]) -> str:
    return ", ".join(
        " ".join(str(v) for v in item.values() if v is not None)
        if isinstance(item, dict)
        else str(item)
        for item in items
    )


def _where_bought(fields: dict[str, Any]) -> str:
    text = str(fields["seller"])
    if fields.get("seller_location"):
        text += f", {fields['seller_location']}"
    if fields.get("order_id"):
        text += f", order ID {fields['order_id']}"
    return text


def _text_of(doc: DocumentRow, name: str, kind: FieldKind, today: date) -> str | None:
    value = doc.fields[name]
    if kind == "date":
        day = _as_date(value)
        if day is None:
            return None
        expiry = DATE_ROLES[doc.doc_type].get("expiry")
        if name == expiry and doc.doc_type in STATUS_TYPES:
            return (
                f"Yes, until {format_date(day)}."
                if day >= today
                else (f"Ended {format_date(day)}.")
            )
        return format_date(day)
    if kind == "amount":
        amount = _as_amount(value)
        return None if amount is None else format_amount(amount)
    if name == "warranty_parts" and doc.doc_type is DocType.warranty_card:
        return _warranty_text(doc, today)
    if name == "seller":
        return _where_bought(doc.fields)
    if isinstance(value, list):
        return _list_text(value)
    return str(value)


def _supporting(
    doc: DocumentRow, name: str, kind: FieldKind, lines: list[StoredLine]
) -> list[LineRef]:
    if name == "warranty_parts" and doc.doc_type is DocType.warranty_card:
        # A part has to be on the page; the purchase date line (where its cover starts) is
        # cited with it but never supports the answer on its own.
        refs = locate(doc.fields[name], "list", lines)
        if not refs:
            return []
        refs += locate(doc.fields.get("purchase_date"), "date", lines)
        return sorted(set(refs), key=lambda r: (r.page, r.idx))
    return locate(doc.fields[name], kind, lines)


def weak_match(query: Query, rows: Sequence[Row]) -> bool:
    """Whether the rows are too thin to answer from. A query with residual words needs a row
    that matches them (a keyword hit or a vector score of MIN_VECTOR or more). A query with no
    filter behind it also needs a top row with some evidence. A row the filters found is a real
    candidate on its own only when the query has no residual words."""
    if not rows:
        return False
    if query.words.strip() and not any(r.word_hit or r.vector >= MIN_VECTOR for r in rows):
        return True
    # the row an answer would come from: the best one that passes the person and type filters
    top = next((r for r in rows if _fits(query, r)), rows[0])
    return not _filtered(query) and top.score < MIN_FUSED and len(top.lines) < MIN_KEYWORD


def _fits(query: Query, row: Row) -> bool:
    """Whether a row passes the query's person and type filters (an empty filter passes all)."""
    if query.people and not set(query.people) & set(row.people):
        return False
    return not query.types or row.doc_type in query.types


def compose(
    query: Query, rows: Sequence[Row], store: Store, today: date
) -> Answer | NoAnswer | None:
    """The answer to a lookup, read from the top row's stored fields; `None` for a list, or a
    find or a lookup that names no field and has evidence (they show rows only).

    A find or a lookup is declined, with the closest files, when it names a person the household
    does not hold (`unknown_person`), when no row is for the person and type asked
    (`no_documents`, also for no rows) or when the evidence is weak (`weak_match`).
    """
    if query.intent == "list":
        return None
    closest = [r.rel_path for r in rows[:3]]
    if any(u.startswith("person:") for u in query.unread):
        # a person the household does not hold: an empty person filter would answer from
        # whoever's document ranks first, which is another member's value
        return NoAnswer("unknown_person", closest)
    if not rows:
        return NoAnswer("no_documents", [])
    if weak_match(query, rows):
        return NoAnswer("weak_match", closest)
    if (query.people or query.types) and not any(_fits(query, r) for r in rows):
        # the rows come from the unfiltered votes; none is for the person and type asked
        return NoAnswer("no_documents", closest)
    if query.intent != "lookup" or query.field is None:
        return None
    # The unfiltered votes may put a document the reading excluded on top; an answer comes from
    # the best row that passes the person and type filters, or there is none.
    top = next((r for r in rows if _fits(query, r)), None)
    if top is None:
        return NoAnswer("no_documents", closest)
    doc = store.document(top.document_id)
    schema = SCHEMAS.get(doc.doc_type) if doc is not None else None
    if doc is None or schema is None:
        return NoAnswer("no_documents", closest)
    name = field_for(doc.doc_type, query.field, schema.model_fields)
    if name is None or doc.fields.get(name) in (None, "", []):
        return NoAnswer("no_field", closest)
    kind = field_kind(schema, name)
    text = _text_of(doc, name, kind, today)
    if text is None:
        return NoAnswer("no_field", closest)
    refs = _supporting(doc, name, kind, store.lines_of(doc.id))
    if not refs:
        return NoAnswer("not_on_page", closest)
    return Answer(
        text=text,
        field=name,
        value=doc.fields[name],
        document_id=doc.id,
        page=refs[0].page,
        lines=refs,
        masked=(doc.doc_type, name) in MASKED_FIELDS,
    )
