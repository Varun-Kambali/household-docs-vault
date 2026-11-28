"""Date arithmetic shared by search answers and reminders."""

import calendar
import re
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from household_vault.search.dates import add_months

_NUMERIC = re.compile(r"(\d{1,2})\s*/\s*(\d{2}|\d{4})")
_WORDS = re.compile(r"([A-Za-z]{3,9})\.?\s+(\d{4})")


def part_end(start: date, years: Decimal) -> date:
    """The last covered day: the purchase date plus the part's years, less one day, the way
    the policies print their ends. A fraction counts as whole months; an anniversary on 29 Feb
    falls on 28 Feb in a year without one."""
    months = int((years * 12).to_integral_value(ROUND_HALF_UP))
    return add_months(start, months) - timedelta(days=1)


def _month_end(year: int, month: int) -> date | None:
    if not 1 <= month <= 12 or not 1 <= year <= 9999:
        return None
    return date(year, month, calendar.monthrange(year, month)[1])


def card_expiry_end(text: str) -> date | None:
    """The last day of the month a card prints as its expiry ("06/31", "06/2031", "Jun 2031").
    Anything else gives None."""
    if not isinstance(text, str):
        return None
    text = text.strip()
    if m := _NUMERIC.fullmatch(text):
        year = int(m[2])
        return _month_end(year + 2000 if len(m[2]) == 2 else year, int(m[1]))
    if m := _WORDS.fullmatch(text):
        word = m[1].lower()
        for month in range(1, 13):
            if calendar.month_name[month].lower().startswith(word) and len(word) >= 3:
                return _month_end(int(m[2]), month)
    return None
