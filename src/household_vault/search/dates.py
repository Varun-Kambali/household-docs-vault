"""Date phrases a person types, worked out by code. The reading model only copies the words;
it never works out a date."""

from __future__ import annotations

import calendar
import re
from datetime import date, timedelta

from pydantic import BaseModel, ConfigDict

from household_vault.schemas._coerce import parse_date


class DateRange(BaseModel):
    """Both ends inclusive; a missing end is open."""

    model_config = ConfigDict(frozen=True)

    start: date | None = None
    end: date | None = None


_MONTHS: dict[str, int] = {
    **{name.lower(): i for i, name in enumerate(calendar.month_name) if name},
    **{name.lower(): i for i, name in enumerate(calendar.month_abbr) if name},
    "sept": 9,
}
_MONTH = "|".join(sorted(_MONTHS, key=len, reverse=True))
_MONTH_PHRASE = re.compile(rf"(?:(before|by|until|till|in)\s+)?({_MONTH})(?:\s+(\d{{4}}))?")
_PREFIXED = re.compile(r"(before|by|until|till)\s+(.+)")
_SPAN = re.compile(r"(this|next|last)\s+(month|year)")
_NEXT_N = re.compile(r"next\s+(\d{1,3})\s+(day|week|month)s?")
_DAY_MONTH_NAME = re.compile(rf"(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH})")
_DAY_MONTH_NUM = re.compile(r"(\d{1,2})/(\d{1,2})")
_EDGES = re.compile(r"^[\W_]+|[\W_]+$")
_YEAR_SPAN = re.compile(r"(fy|ay)\s*(\d{4})\s*-\s*(\d{2}|\d{4})")


def _last_day(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _add_months(day: date, months: int) -> date:
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def _month_range(preposition: str | None, month: int, year: int) -> DateRange:
    first, last = date(year, month, 1), _last_day(year, month)
    if preposition == "before":
        return DateRange(start=None, end=first - timedelta(days=1))
    if preposition in ("by", "until", "till"):
        return DateRange(start=None, end=last)
    return DateRange(start=first, end=last)  # "in March", or March alone: the whole month


def _span(which: str, unit: str, today: date) -> DateRange:
    step = {"this": 0, "next": 1, "last": -1}[which]
    if unit == "year":
        year = today.year + step
        return DateRange(start=date(year, 1, 1), end=date(year, 12, 31))
    first = _add_months(today.replace(day=1), step)
    return DateRange(start=first, end=_last_day(first.year, first.month))


def _financial_year(kind: str, start_year: int, end_text: str) -> DateRange | None:
    end_year = int(end_text)
    if len(end_text) == 2:
        end_year += start_year // 100 * 100
        if end_year <= start_year:  # 2099-00 wraps into the next century
            end_year += 100
    if end_year != start_year + 1:
        return None
    if kind == "ay":  # the assessment year follows the financial year it assesses
        start_year, end_year = start_year - 1, end_year - 1
    return DateRange(start=date(start_year, 4, 1), end=date(end_year, 3, 31))


def _printed(text: str) -> date | None:
    try:
        return parse_date(text)
    except ValueError:
        return None


def _day_month(text: str, today: date) -> date | None:
    """A day and month with no year: its next occurrence, counting today."""
    if m := _DAY_MONTH_NAME.fullmatch(text):
        day, month = int(m.group(1)), _MONTHS[m.group(2)]
    elif m := _DAY_MONTH_NUM.fullmatch(text):
        day, month = int(m.group(1)), int(m.group(2))
    else:
        return None
    for year in range(today.year, today.year + 9):  # far enough to reach a 29 February
        try:
            found = date(year, month, day)
        except ValueError:
            continue
        if found >= today:
            return found
    return None


def parse_date_phrase(phrase: str, today: date) -> DateRange | None:
    """The span a phrase means, or `None` when code cannot read it (the caller reports it).
    Never raises: a year outside what a date can hold reads as `None`."""
    try:
        return _parse(phrase, today)
    except (ValueError, OverflowError):
        return None


def _parse(phrase: str, today: date) -> DateRange | None:
    text = _EDGES.sub("", re.sub(r"\s+", " ", phrase.lower())).strip()
    if not text:
        return None
    if m := _YEAR_SPAN.fullmatch(text):
        return _financial_year(m.group(1), int(m.group(2)), m.group(3))
    if m := _SPAN.fullmatch(text):
        return _span(m.group(1), m.group(2), today)
    if m := _NEXT_N.fullmatch(text):
        n, unit = int(m.group(1)), m.group(2)
        if n == 0:
            return None
        if unit == "month":
            return DateRange(start=today, end=_add_months(today, n))
        return DateRange(start=today, end=today + timedelta(days=n * (7 if unit == "week" else 1)))
    if m := _MONTH_PHRASE.fullmatch(text):
        preposition, month = m.group(1), _MONTHS[m.group(2)]
        if m.group(3):
            year = int(m.group(3))
        elif preposition == "before":  # the next one whose first day is still ahead
            year = today.year + (date(today.year, month, 1) <= today)
        else:
            year = today.year + (month < today.month)
        return _month_range(preposition, month, year)
    prefix = _PREFIXED.fullmatch(text)
    body = prefix.group(2) if prefix else text
    printed = _printed(body) or _day_month(body, today)
    if printed is None:
        return None
    if prefix is None:
        return DateRange(start=printed, end=printed)
    if prefix.group(1) == "before":
        return DateRange(start=None, end=printed - timedelta(days=1))
    return DateRange(start=None, end=printed)
