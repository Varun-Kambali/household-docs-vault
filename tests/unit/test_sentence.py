from datetime import date

import pytest
from vault_synth.household import HOUSEHOLD

from household_vault.doctypes import Area, DocType
from household_vault.search.dates import DateRange
from household_vault.search.query import Query
from household_vault.search.sentence import Part, apply_part, render, sentence

TODAY = date(2026, 11, 21)


@pytest.fixture
def household():
    return HOUSEHOLD


def list_query(**fields) -> Query:
    return Query(**{"intent": "list", **fields})


def part(s, slot: str) -> Part:
    return next(p for p in s.parts if p.slot == slot)


def test_the_sentence_shows_dates_and_a_change_needs_no_model(household):
    q = list_query(role="expiry", range=DateRange(start=TODAY, end=date(2027, 2, 28)))
    assert "between 21 Nov 2026 and 28 Feb 2027" in render(sentence(q, household, TODAY))
    assert apply_part(q, "who", "p2", TODAY).people == ["p2"]


def test_the_sentence_reads_in_the_fixed_shape(household):
    q = list_query(
        people=["p1", "p2"],
        types=[DocType.health_policy],
        role="expiry",
        range=DateRange(start=TODAY, end=date(2027, 2, 28)),
        place="Star Health",
    )
    assert render(sentence(q, household, TODAY)) == (
        "Showing health insurance policies for Ravi Kumar Rao and Kavita Rao that expire "
        "between 21 Nov 2026 and 28 Feb 2027 from Star Health"
    )


def test_an_empty_query_reads_as_everything_for_everyone(household):
    assert render(sentence(list_query(), household, TODAY)) == (
        "Showing documents for everyone that are dated any time"
    )


def test_what_names_the_types_or_the_areas(household):
    by_area = sentence(list_query(areas=[Area.insurance]), household, TODAY)
    assert part(by_area, "what").text == "insurance documents"
    two = sentence(list_query(types=[DocType.pan, DocType.passport]), household, TODAY)
    assert part(two, "what").text == "PAN cards and passports"


def test_when_reads_each_shape_of_range(household):
    def when(**kw):
        return part(sentence(list_query(**kw), household, TODAY), "when").text

    assert when(range=DateRange(end=date(2027, 1, 31))) == "by 31 Jan 2027"
    assert when(range=DateRange(start=date(2027, 1, 1))) == "from 1 Jan 2027"
    assert when(range=DateRange(start=date(2027, 1, 1), end=date(2027, 1, 1))) == "on 1 Jan 2027"
    assert when() == "any time"


def test_the_verb_follows_the_role(household):
    def verb(role):
        return part(sentence(list_query(role=role), household, TODAY), "verb").text

    assert [verb(r) for r in ("expiry", "renewal", "due", "purchase", "issue", "document")] == [
        "expire", "renew", "fall due", "were bought", "were issued", "are dated",
    ]  # fmt: skip


def test_the_dropdowns_offer_the_choices(household):
    s = sentence(list_query(place="Star Health"), household, TODAY)
    who = [o.label for o in part(s, "who").options]
    assert who[0] == "everyone" and "Kavita Rao" in who
    when = [o.label for o in part(s, "when").options]
    assert when[:5] == ["any time", "next 30 days", "next 60 days", "this month", "this year"]
    assert [o for o in when if o.startswith("before ")] == [
        "before 1 Dec 2026", "before 1 Jan 2027", "before 1 Feb 2027",
        "before 1 Mar 2027", "before 1 Apr 2027", "before 1 May 2027",
    ]  # fmt: skip
    assert when[-1] == "a custom range"
    assert {o.value for o in part(s, "verb").options} >= {"expiry", "renewal", "due"}
    what = [o.label for o in part(s, "what").options]
    assert what[0] == "all documents" and "insurance" in what
    assert part(s, "place").options == []


def test_no_place_part_when_none_is_set(household):
    assert [p.slot for p in sentence(list_query(), household, TODAY).parts] == [
        "what", "who", "verb", "when",
    ]  # fmt: skip


def test_an_unknown_person_id_still_reads(household):
    s = sentence(list_query(people=["home", "p9"]), household, TODAY)
    assert part(s, "who").text == "the household and p9"


def test_changing_who_what_verb_and_place(household):
    q = list_query(people=["p1"], types=[DocType.pan], role="expiry", place="Star")
    assert apply_part(q, "who", [], TODAY).people == []
    assert apply_part(q, "who", ["p1", "p3"], TODAY).people == ["p1", "p3"]
    assert apply_part(q, "what", "all", TODAY).types == []
    changed = apply_part(q, "what", "area:insurance", TODAY)
    assert (changed.types, changed.areas) == ([], [Area.insurance])
    changed = apply_part(q, "what", "type:passport", TODAY)
    assert (changed.types, changed.areas) == ([DocType.passport], [])
    assert apply_part(q, "verb", "renewal", TODAY).role == "renewal"
    assert apply_part(q, "place", None, TODAY).place is None
    assert apply_part(q, "place", "Digit", TODAY).place == "Digit"
    assert q.people == ["p1"]  # the original is untouched


def test_when_presets(household):
    q = list_query(role="expiry")

    def rng(value):
        return apply_part(q, "when", value, TODAY).range

    assert rng("any") is None
    assert rng("next_30") == DateRange(start=TODAY, end=date(2026, 12, 21))
    assert rng("next_60") == DateRange(start=TODAY, end=date(2027, 1, 20))
    assert rng("this_month") == DateRange(start=date(2026, 11, 1), end=date(2026, 11, 30))
    assert rng("this_year") == DateRange(start=date(2026, 1, 1), end=date(2026, 12, 31))
    assert rng("before:2027-03-01") == DateRange(end=date(2027, 2, 28))
    assert rng({"start": "2027-01-01", "end": "2027-02-28"}) == DateRange(
        start=date(2027, 1, 1), end=date(2027, 2, 28)
    )
    assert rng({"start": None, "end": "2027-02-28"}) == DateRange(end=date(2027, 2, 28))
    assert apply_part(q, "when", "next_30", TODAY).role == "expiry"


def test_a_bad_change_is_refused(household):
    q = list_query()
    for slot, value in (("when", "soon"), ("what", "type:nope"), ("verb", "sing"), ("how", "x")):
        with pytest.raises(ValueError):
            apply_part(q, slot, value, TODAY)
    with pytest.raises(ValueError):
        apply_part(q, "when", {"start": "not a date", "end": None}, TODAY)


def test_every_option_is_accepted_by_apply_part(household):
    q = list_query(role="expiry")
    s = sentence(q, household, TODAY)
    for p in s.parts:
        for o in p.options:
            if o.value == "custom":
                continue
            apply_part(q, p.slot, o.value, TODAY)


def test_a_custom_range_with_both_ends_empty_clears_the_date_filter(household):
    q = list_query(role="expiry", range=DateRange(end=date(2027, 2, 28)))
    assert apply_part(q, "when", {"start": None, "end": None}, TODAY).range is None
