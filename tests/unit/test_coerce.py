from datetime import date
from decimal import Decimal

import pytest

from household_vault.schemas._coerce import parse_amount, parse_date


@pytest.mark.parametrize(
    "text",
    [
        "14.03.2024",
        "14-Mar-2024",
        "14/03/24",
        "14-03-24",
        "14.03.24",
        "Mar 14, 2024",
        "March 14, 2024",
        "14th March 2024",
        "14 mar 2024",
        "  14  March   2024 ",
        "2024-03-14T00:00:00",
        "2024-03-14",
        "14/03/2024",
        "14 Mar 2024",
    ],
)
def test_indian_date_forms(text):
    assert parse_date(text) == date(2024, 3, 14)


def test_sept_reads_as_sep_and_two_digit_years_follow_percent_y():
    assert parse_date("14 Sept 2024") == date(2024, 9, 14)
    assert parse_date("01/01/69") == date(1969, 1, 1)
    assert parse_date("01/01/68") == date(2068, 1, 1)


def test_dates_are_day_first():
    assert parse_date("03/04/2024") == date(2024, 4, 3)


@pytest.mark.parametrize("text", ["next spring", "31/02/2024", "", "2024-13-01"])
def test_unreadable_dates_raise_without_repeating_the_value(text):
    with pytest.raises(ValueError) as err:
        parse_date(text)
    assert text not in str(err.value) or text == ""


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("Rs. 35,400/-", 35400),
        ("5 Lakhs", 500000),
        ("1.5 Cr", 15000000),
        ("Rupees 5000", 5000),
        ("Rs. 5,000 only", 5000),
        ("12,34,567", 1234567),
        ("1,234,567", 1234567),
        ("₹ 5,00,000", 500000),
        ("INR 1200", 1200),
        ("rs 1200", 1200),
        ("2 crore", 20000000),
        ("3 lac", 300000),
        ("2 L", 200000),
        ("20%", 20),
        ("1,234.50", Decimal("1234.50")),
    ],
)
def test_indian_amount_forms(text, value):
    assert parse_amount(text) == Decimal(value)


@pytest.mark.parametrize(
    "text", ["12,34", "-500", "Rupees five thousand only", "abc", "", "1,2,3", "12,3456"]
)
def test_unreadable_amounts_raise(text):
    with pytest.raises(ValueError):
        parse_amount(text)


def test_numbers_and_negative_numbers():
    assert parse_amount(5000) == Decimal(5000)
    assert parse_amount(12.5) == Decimal("12.5")
    for bad in (-1, True, float("nan"), Decimal("-2")):
        with pytest.raises(ValueError):
            parse_amount(bad)
