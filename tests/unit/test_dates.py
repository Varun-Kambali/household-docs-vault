from datetime import date, timedelta

import pytest

from household_vault.search.dates import DateRange, parse_date_phrase

TODAY = date(2026, 11, 21)


def test_date_phrases_around_the_year_end():  # Review Focus 15
    dec = date(2026, 12, 15)
    assert parse_date_phrase("before March", dec) == DateRange(start=None, end=date(2027, 2, 28))
    assert parse_date_phrase("by March", dec) == DateRange(start=None, end=date(2027, 3, 31))
    assert parse_date_phrase("this year", date(2027, 1, 1)) == DateRange(
        start=date(2027, 1, 1), end=date(2027, 12, 31)
    )
    assert parse_date_phrase("FY 2025-26", dec) == DateRange(
        start=date(2025, 4, 1), end=date(2026, 3, 31)
    )
    assert parse_date_phrase("next 60 days", dec) == DateRange(start=dec, end=dec + timedelta(60))
    assert parse_date_phrase("before Diwali", dec) is None


def test_a_month_with_no_year_is_its_next_occurrence_counting_this_month():
    assert parse_date_phrase("by November", TODAY) == DateRange(start=None, end=date(2026, 11, 30))
    assert parse_date_phrase("in November", TODAY) == DateRange(
        start=date(2026, 11, 1), end=date(2026, 11, 30)
    )
    assert parse_date_phrase("in January", TODAY) == DateRange(
        start=date(2027, 1, 1), end=date(2027, 1, 31)
    )
    assert parse_date_phrase("until Feb 2028", TODAY) == DateRange(
        start=None, end=date(2028, 2, 29)
    )
    assert parse_date_phrase("till sept", TODAY) == DateRange(start=None, end=date(2027, 9, 30))


def test_before_a_month_ends_the_day_before_its_first_day():
    assert parse_date_phrase("before January", TODAY) == DateRange(
        start=None, end=date(2026, 12, 31)
    )
    assert parse_date_phrase("before March 2024", TODAY) == DateRange(
        start=None, end=date(2024, 2, 29)
    )


def test_this_next_and_last_are_calendar_spans():
    assert parse_date_phrase("this month", TODAY) == DateRange(
        start=date(2026, 11, 1), end=date(2026, 11, 30)
    )
    assert parse_date_phrase("next month", TODAY) == DateRange(
        start=date(2026, 12, 1), end=date(2026, 12, 31)
    )
    assert parse_date_phrase("last month", date(2027, 1, 5)) == DateRange(
        start=date(2026, 12, 1), end=date(2026, 12, 31)
    )
    assert parse_date_phrase("last year", TODAY) == DateRange(
        start=date(2025, 1, 1), end=date(2025, 12, 31)
    )
    assert parse_date_phrase("next year", TODAY) == DateRange(
        start=date(2027, 1, 1), end=date(2027, 12, 31)
    )


def test_next_n_units_run_from_today():
    assert parse_date_phrase("next 2 weeks", TODAY) == DateRange(
        start=TODAY, end=TODAY + timedelta(14)
    )
    assert parse_date_phrase("next 3 months", TODAY) == DateRange(
        start=TODAY, end=date(2027, 2, 21)
    )
    assert parse_date_phrase("next 1 month", date(2026, 1, 31)) == DateRange(
        start=date(2026, 1, 31), end=date(2026, 2, 28)
    )


def test_printed_dates_go_through_parse_date():
    d = date(2025, 3, 4)
    assert parse_date_phrase("04/03/2025", TODAY) == DateRange(start=d, end=d)
    assert parse_date_phrase("4 March 2025", TODAY) == DateRange(start=d, end=d)
    assert parse_date_phrase("before 4 March 2025", TODAY) == DateRange(
        start=None, end=date(2025, 3, 3)
    )


def test_financial_and_assessment_years():
    assert parse_date_phrase("FY 2025-26", TODAY) == parse_date_phrase("fy2025-2026", TODAY)
    assert parse_date_phrase("AY 2026-27", TODAY) == DateRange(
        start=date(2025, 4, 1), end=date(2026, 3, 31)
    )


@pytest.mark.parametrize(
    "phrase",
    ["", "soon", "before Diwali", "next Tuesday", "FY 2025-28", "next 0 days", "99/99/2025"],
)
def test_anything_else_is_none(phrase):
    assert parse_date_phrase(phrase, TODAY) is None


@pytest.mark.parametrize(
    "phrase",
    [
        "in march 0000",
        "FY 0000-01",
        "AY 0001-02",
        "before january 0001",
        "before 01/01/0001",
    ],
)
def test_year_edge_input_is_none_never_an_error(phrase):
    assert parse_date_phrase(phrase, TODAY) is None


def test_before_a_month_with_no_year_is_the_next_one_that_starts_after_today():
    assert parse_date_phrase("before November", TODAY) == DateRange(
        start=None, end=date(2027, 10, 31)
    )
    dec = date(2026, 12, 15)
    assert parse_date_phrase("before March", dec) == DateRange(start=None, end=date(2027, 2, 28))
    assert parse_date_phrase("before December", date(2026, 11, 30)) == DateRange(
        start=None, end=date(2026, 11, 30)
    )
    assert parse_date_phrase("before November 2026", TODAY) == DateRange(
        start=None, end=date(2026, 10, 31)
    )


def test_a_day_and_month_with_no_year_is_its_next_occurrence_counting_today():
    assert parse_date_phrase("by 31 March", TODAY) == DateRange(start=None, end=date(2027, 3, 31))
    assert parse_date_phrase("31 Mar", TODAY) == DateRange(
        start=date(2027, 3, 31), end=date(2027, 3, 31)
    )
    assert parse_date_phrase("31/03", TODAY) == DateRange(
        start=date(2027, 3, 31), end=date(2027, 3, 31)
    )
    assert parse_date_phrase("21 November", TODAY) == DateRange(start=TODAY, end=TODAY)
    assert parse_date_phrase("20 November", TODAY) == DateRange(
        start=date(2027, 11, 20), end=date(2027, 11, 20)
    )
    assert parse_date_phrase("before 31 March", TODAY) == DateRange(
        start=None, end=date(2027, 3, 30)
    )
    assert parse_date_phrase("29 February", TODAY) == DateRange(
        start=date(2028, 2, 29), end=date(2028, 2, 29)
    )
    assert parse_date_phrase("31/02", TODAY) is None
    assert parse_date_phrase("31 April", TODAY) is None


def test_punctuation_and_repeated_spaces_are_ignored():
    assert parse_date_phrase("next 2 weeks.", TODAY) == parse_date_phrase("next 2 weeks", TODAY)
    assert parse_date_phrase("  before   March? ", TODAY) == parse_date_phrase(
        "before March", TODAY
    )
    assert parse_date_phrase("(this year)!", TODAY) == parse_date_phrase("this year", TODAY)
    assert parse_date_phrase("?!", TODAY) is None


def test_two_digit_financial_year_end_wraps_the_century():
    assert parse_date_phrase("FY 2099-00", TODAY) == DateRange(
        start=date(2099, 4, 1), end=date(2100, 3, 31)
    )
