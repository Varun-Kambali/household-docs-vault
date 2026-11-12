"""Forgiving parsers for the dates and amounts a model or a printed page spells in many ways."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any

from pydantic import BeforeValidator

_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%d %B %Y")
_AMOUNT_NOISE = re.compile(r"₹|rs\.?|inr|%|,|\s", re.IGNORECASE)


def parse_date(value: Any) -> date:
    """ISO, dd/mm/yyyy, dd-mm-yyyy and '14 Mar 2024'. Raises ValueError on anything else."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = re.sub(r"\s+", " ", value.strip())
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
    raise ValueError(f"not a date: {value!r}")


def parse_amount(value: Any) -> Decimal:
    """Drops the rupee sign, 'Rs.', commas, spaces and a percent sign, then reads a number."""
    if isinstance(value, bool):
        raise ValueError(f"not an amount: {value!r}")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int | float):
        return Decimal(str(value))
    if isinstance(value, str):
        try:
            return Decimal(_AMOUNT_NOISE.sub("", value))
        except InvalidOperation:
            pass
    raise ValueError(f"not an amount: {value!r}")


def to_text(value: Any) -> Any:
    """A model may print 12.2 where the page says '12.2'; keep numbers as their text."""
    if isinstance(value, int | float) and not isinstance(value, bool):
        return str(value)
    return value


Text = Annotated[str, BeforeValidator(to_text)]
FlexDate = Annotated[date, BeforeValidator(parse_date)]
Amount = Annotated[Decimal, BeforeValidator(parse_amount)]
