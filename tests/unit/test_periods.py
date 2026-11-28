from datetime import date
from decimal import Decimal

import pytest

from household_vault.periods import card_expiry_end, part_end


def test_part_end_is_the_day_before_the_anniversary():
    assert part_end(date(2024, 3, 14), Decimal(10)) == date(2034, 3, 13)
    assert part_end(date(2024, 2, 29), Decimal(1)) == date(2025, 2, 27)
    assert part_end(date(2024, 3, 14), Decimal("1.5")) == date(2025, 9, 13)


@pytest.mark.parametrize(
    ("text", "end"),
    [
        ("06/31", date(2031, 6, 30)),
        ("06/2031", date(2031, 6, 30)),
        ("Jun 2031", date(2031, 6, 30)),
        ("02/28", date(2028, 2, 29)),
        (" 12/30 ", date(2030, 12, 31)),
    ],
)
def test_card_expiry_is_the_last_day_of_its_month(text, end):
    assert card_expiry_end(text) == end


@pytest.mark.parametrize(
    "text", ["6/31x", "", "June", "13/31", "00/31", "Foo 2031", "Marx 2031", "06/31/2031"]
)
def test_unreadable_card_expiry_is_none(text):
    assert card_expiry_end(text) is None


def test_card_expiry_of_a_non_string_is_none():
    assert card_expiry_end(None) is None  # type: ignore[arg-type]
