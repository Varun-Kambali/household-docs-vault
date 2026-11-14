"""Forgiving parsers for the dates and amounts a model or a printed page spells in many ways,
and the annotated field types that say how each field is read, compared and kept secret."""

from __future__ import annotations

import re
import types
import typing
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal, get_args, get_origin

from pydantic import BaseModel, BeforeValidator

from household_vault.checks import luhn_valid

FieldKind = Literal[
    "text", "name", "identifier", "aadhaar", "gstin", "address", "date", "amount", "list"
]

# Day first, always. %y follows Python: 69 to 99 are the 1900s.
_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%d/%m/%y",
    "%d-%m-%y",
    "%d.%m.%y",
    "%d %b %Y",
    "%d %B %Y",
    "%d-%b-%Y",
    "%b %d, %Y",
    "%B %d, %Y",
)
_ORDINAL = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)\b", re.IGNORECASE)
_SEPT = re.compile(r"\bsept\b", re.IGNORECASE)
_ISO_DATETIME = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d")


def parse_date(value: Any) -> date:
    """Day-first dates in the forms Indian documents print, and any ISO datetime.

    Raises ValueError (without the value) on anything else.
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = re.sub(r"\s+", " ", value.strip())
        text = _SEPT.sub("Sep", _ORDINAL.sub(r"\1", text))
        if _ISO_DATETIME.match(text):
            try:
                return datetime.fromisoformat(text).date()
            except ValueError:
                pass
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
    raise ValueError("not a date")


_CURRENCY_WORD = re.compile(r"(?<![a-z])(?:rupees|rs|inr)(?![a-z])\.?")
_MULTIPLIER = re.compile(r"^([\d,.\s]+?)\s*(lakhs?|lacs?|l|crores?|cr)\.?$")
_PLAIN = re.compile(r"\d+(?:\.\d+)?|\.\d+")
_WESTERN = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?")
_INDIAN = re.compile(r"\d{1,2}(?:,\d{2})*,\d{3}(?:\.\d+)?")


def parse_amount(value: Any) -> Decimal:
    """Rupee amounts: drops the sign, Rs, INR, Rupees, '/-', 'only', spaces and a percent sign.

    Commas only in western (1,234,567) or Indian (12,34,567) grouping. Lakh, lac and L multiply
    by 100,000; crore and cr by 10,000,000. A negative amount raises ValueError.
    """
    if isinstance(value, bool):
        raise ValueError("not an amount")
    if isinstance(value, int | float | Decimal):
        number = Decimal(str(value)) if not isinstance(value, Decimal) else value
        if number.is_finite() and number >= 0:
            return number
        raise ValueError("not an amount")
    if isinstance(value, str):
        text = value.lower().replace("₹", " ")
        text = _CURRENCY_WORD.sub(" ", text).replace("%", " ").strip()
        while True:
            trimmed = re.sub(r"(?:/-|only)\s*$", "", text).strip()
            if trimmed == text:
                break
            text = trimmed
        factor = Decimal(1)
        m = _MULTIPLIER.match(text)
        if m:
            text = m.group(1)
            factor = Decimal(100_000 if m.group(2).startswith("l") else 10_000_000)
        text = re.sub(r"\s+", "", text)
        if "," in text and not (_WESTERN.fullmatch(text) or _INDIAN.fullmatch(text)):
            raise ValueError("not an amount")
        text = text.replace(",", "")
        if _PLAIN.fullmatch(text):
            try:
                return Decimal(text) * factor
            except InvalidOperation:
                pass
    raise ValueError("not an amount")


def to_text(value: Any) -> Any:
    """A model may print 12.2 where the page says '12.2'; keep numbers as their text."""
    if isinstance(value, int | float) and not isinstance(value, bool):
        return str(value)
    return value


def _digits_only(value: Any) -> str:
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str):
        raise ValueError("not a number")
    return re.sub(r"[\s-]", "", value)


def to_card_number(value: Any) -> str:
    """Digits only, 13 to 19 of them, passing Luhn."""
    digits = _digits_only(value)
    if not (digits.isdigit() and 13 <= len(digits) <= 19 and luhn_valid(digits)):
        raise ValueError("not a card number")
    return digits


def to_cvv(value: Any) -> str:
    digits = _digits_only(value)
    if not (digits.isdigit() and len(digits) in (3, 4)):
        raise ValueError("not a CVV")
    return digits


@dataclass(frozen=True)
class Kind:
    """Annotated metadata: how a field's text is compared."""

    kind: FieldKind


@dataclass(frozen=True)
class SecretField:
    """Annotated metadata: the value never reaches the database, a log or a results file."""


Text = Annotated[str, BeforeValidator(to_text), Kind("text")]
Name = Annotated[str, BeforeValidator(to_text), Kind("name")]
Identifier = Annotated[str, BeforeValidator(to_text), Kind("identifier")]
AadhaarNumber = Annotated[str, BeforeValidator(to_text), Kind("aadhaar")]
Gstin = Annotated[str, BeforeValidator(to_text), Kind("gstin")]
Address = Annotated[str, BeforeValidator(to_text), Kind("address")]
FlexDate = Annotated[date, BeforeValidator(parse_date), Kind("date")]
Amount = Annotated[Decimal, BeforeValidator(parse_amount), Kind("amount")]
CardNumber = Annotated[str, BeforeValidator(to_card_number), Kind("identifier"), SecretField()]
Cvv = Annotated[str, BeforeValidator(to_cvv), Kind("identifier"), SecretField()]


def _members(annotation: Any) -> list[Any]:
    """The parts of an annotation, looking through `X | None` and Annotated wrappers."""
    if get_origin(annotation) is Annotated:
        return _members(get_args(annotation)[0])
    if get_origin(annotation) in (typing.Union, types.UnionType):
        return [m for arg in get_args(annotation) for m in _members(arg)]
    return [annotation]


def _markers(annotation: Any) -> list[Any]:
    """Every Annotated marker in an annotation, looking through unions like `Text | None`."""
    if get_origin(annotation) is Annotated:
        args = get_args(annotation)
        return [*args[1:], *_markers(args[0])]
    if get_origin(annotation) in (typing.Union, types.UnionType):
        return [m for arg in get_args(annotation) for m in _markers(arg)]
    return []


def field_kind(schema: type[BaseModel], name: str) -> FieldKind:
    """How the field is compared: its Kind marker, 'list' for a list, else 'text'."""
    annotation = schema.model_fields[name].annotation
    for marker in _markers(annotation):
        if isinstance(marker, Kind):
            return marker.kind
    return "list" if any(get_origin(m) is list for m in _members(annotation)) else "text"


def secret_fields(schema: type[BaseModel]) -> frozenset[str]:
    return frozenset(
        name
        for name, info in schema.model_fields.items()
        if any(isinstance(m, SecretField) for m in _markers(info.annotation))
    )
