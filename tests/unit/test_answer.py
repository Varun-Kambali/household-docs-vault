from datetime import date
from decimal import Decimal

import pytest

from evals.search_set import EVAL_TODAY, STATUS_TYPES, status_of
from household_vault.db import StoredLine
from household_vault.doctypes import DocType
from household_vault.search import answer as answer_module
from household_vault.search.answer import (
    Answer,
    NoAnswer,
    compose,
    format_amount,
    format_date,
    locate,
)
from household_vault.search.dates import DateRange
from household_vault.search.query import Query
from household_vault.search.retrieve import LineRef, Row
from tests.conftest import add_doc

TODAY = date(2026, 11, 20)


def query(**fields) -> Query:
    return Query(**{"intent": "lookup", **fields})


def stored_line(text: str, idx: int = 0, page: int = 0) -> StoredLine:
    return StoredLine(page, idx, text, (0.0, 0.1 * idx, 1.0, 0.1 * idx + 0.1))


def make_rows(
    store,
    doc_type: DocType,
    fields: dict,
    lines: list[str],
    doc_id: str = "d1",
    score: float = 0.05,
) -> list[Row]:
    add_doc(store, doc_id, doc_type.value, fields, lines)
    doc = store.document(doc_id)
    return [
        Row(
            document_id=doc_id,
            doc_type=doc.doc_type,
            owner=doc.owner,
            people=[doc.owner],
            area=doc.area,
            rel_path=doc.rel_path,
            doc_date=doc.doc_date,
            key_fields={},
            date=None,
            score=score,
            lines=[],
        )
    ]


def warranty_rows(store, purchase_date, parts, lines=None, **kwargs):
    fields = {
        "brand": "LG",
        "product": "Refrigerator",
        "purchase_date": purchase_date.isoformat(),
        "warranty_parts": [{"part": name, "years": years} for name, years in parts],
    }
    printed = lines or [
        "LG Refrigerator",
        f"Purchase date: {purchase_date.strftime('%d/%m/%Y')}",
        *[f"{name} warranty {years} years" for name, years in parts],
    ]
    return make_rows(store, DocType.warranty_card, fields, printed, **kwargs)


# -- warranty parts and status -----------------------------------------------------------------


def test_a_warranty_with_parts_answers_part_by_part(store):
    rows = warranty_rows(store, date(2024, 3, 14), parts=[("Compressor", 10), ("Comprehensive", 1)])
    a = compose(query(field="warranty_parts"), rows, store, date(2026, 11, 20))
    assert a.text == "Compressor: yes, until 13 Mar 2034. Comprehensive: ended 13 Mar 2025."
    assert a.field == "warranty_parts"
    assert a.value == [{"part": "Compressor", "years": 10}, {"part": "Comprehensive", "years": 1}]
    assert not a.masked and a.document_id == "d1" and a.lines


def test_a_part_still_holds_on_its_end_day(store):
    rows = warranty_rows(store, date(2024, 3, 14), parts=[("Comprehensive", 1)])
    on_the_day = compose(query(field="warranty_parts"), rows, store, date(2025, 3, 13))
    after = compose(query(field="warranty_parts"), rows, store, date(2025, 3, 14))
    assert on_the_day.text == "Comprehensive: yes, until 13 Mar 2025."
    assert after.text == "Comprehensive: ended 13 Mar 2025."


def test_a_part_ends_the_day_before_its_anniversary_a_leap_day_anniversary_on_the_28th(store):
    rows = warranty_rows(store, date(2024, 2, 29), parts=[("Panel", 1)])
    a = compose(query(field="warranty_parts"), rows, store, date(2026, 1, 1))
    assert a.text == "Panel: ended 27 Feb 2025."


def test_a_part_with_a_fraction_of_a_year_counts_whole_months(store):
    rows = warranty_rows(store, date(2024, 3, 14), parts=[("Motor", 1.5), ("Panel", 0.5)])
    a = compose(query(field="warranty_parts"), rows, store, date(2026, 1, 1))
    assert a.text == "Motor: ended 13 Sep 2025. Panel: ended 13 Sep 2024."


def test_a_warranty_without_a_purchase_date_has_no_field_to_answer_from(store):
    rows = make_rows(
        store,
        DocType.warranty_card,
        {"warranty_parts": [{"part": "Motor", "years": 2}]},
        ["Motor warranty 2 years"],
    )
    a = compose(query(field="warranty_parts"), rows, store, TODAY)
    assert a == NoAnswer("no_field", [rows[0].rel_path])


def test_a_warranty_answer_cites_the_part_lines_and_the_purchase_date_line(store):
    rows = warranty_rows(store, date(2024, 3, 14), parts=[("Motor", 2)])
    a = compose(query(field="warranty_parts"), rows, store, TODAY)
    assert [(ref.page, ref.idx) for ref in a.lines] == [(0, 1), (0, 2)]


def test_a_warranty_with_no_part_on_the_page_cites_nothing_and_gives_no_answer(store):
    rows = warranty_rows(
        store, date(2024, 3, 14), parts=[("Motor", 2)], lines=["LG Refrigerator", "Thank you"]
    )
    assert compose(query(field="warranty_parts"), rows, store, TODAY).reason == "not_on_page"


def test_the_app_and_the_eval_agree_on_every_part_around_its_anniversary(store):
    from datetime import timedelta
    from types import SimpleNamespace

    starts = [date(2024, 2, 29), date(2023, 2, 28), date(2024, 3, 1), date(2025, 12, 31),
              date(2024, 3, 14), date(2020, 2, 29)]  # fmt: skip
    n = 0
    for start in starts:
        for years in (1, 2, 4):
            rows = warranty_rows(store, start, [("Part", years)], doc_id=f"w{n}")
            n += 1
            truth = SimpleNamespace(
                doc_type=DocType.warranty_card,
                fields={
                    "purchase_date": start.isoformat(),
                    "warranty_parts": [{"part": "Part", "years": years}],
                },
            )
            anniversary = (
                date(start.year + years, 3, 1)
                if (start.month, start.day) == (2, 29)
                else date(start.year + years, start.month, start.day)
            )
            for offset in range(-3, 4):
                today = anniversary + timedelta(days=offset)
                said = compose(query(field="warranty_parts"), rows, store, today).text
                assert (": yes" in said) == status_of(truth, "warranty_parts", today)["Part"], (
                    start, years, today, said,
                )  # fmt: skip


# -- validity ----------------------------------------------------------------------------------


def policy_rows(store, end, lines=None, **kwargs):
    return make_rows(
        store,
        DocType.health_policy,
        {"insurer": "Star Health", "policy_number": "P/123", "end_date": end.isoformat()},
        lines or ["Star Health", f"Policy ends: {end.strftime('%d-%b-%Y')}"],
        **kwargs,
    )


def test_a_valid_policy_answers_yes_until_the_end(store):
    a = compose(query(field="end_date"), policy_rows(store, date(2027, 3, 31)), store, TODAY)
    assert a.text == "Yes, until 31 Mar 2027."
    assert (a.field, a.value) == ("end_date", "2027-03-31")


def test_an_ended_policy_says_when_it_ended_and_holds_on_its_last_day(store):
    rows = policy_rows(store, date(2026, 11, 20))
    assert compose(query(field="end_date"), rows, store, date(2026, 11, 20)).text.startswith("Yes")
    assert compose(query(field="end_date"), rows, store, date(2026, 11, 21)).text == (
        "Ended 20 Nov 2026."
    )


def test_a_date_that_is_not_a_validity_reads_as_a_plain_date(store):
    rows = make_rows(
        store,
        DocType.tax_invoice,
        {"seller": "Croma", "invoice_date": "2025-02-18"},
        ["Croma", "Invoice Date: 18/02/2025"],
    )
    a = compose(query(field="invoice_date"), rows, store, TODAY)
    assert a.text == "18 Feb 2025" and a.value == "2025-02-18"


def test_the_status_types_are_the_ones_the_eval_judges():
    assert answer_module.STATUS_TYPES == STATUS_TYPES


def test_the_app_and_the_eval_agree_on_what_still_holds(search_world):
    """Every status the eval truth gives for the filed documents is what the app says."""
    checked = 0
    for doc_id, truth in search_world.truth.items():
        for field in ("warranty_parts", *(["end_date", "period_end"])):
            expected = status_of(truth, field)
            if expected is None:
                continue
            stored = search_world.store.document(doc_id)
            rows = [
                Row(
                    doc_id, stored.doc_type, stored.owner, [stored.owner], stored.area,
                    stored.rel_path, stored.doc_date, {}, None, 0.05, [],
                )
            ]  # fmt: skip
            a = compose(query(field=field), rows, search_world.store, EVAL_TODAY)
            assert isinstance(a, Answer), (doc_id, a)
            if field == "warranty_parts":
                said = {
                    chunk.split(":")[0]: ": yes" in chunk
                    for chunk in a.text.rstrip(".").split(". ")
                }
                assert said == expected
            else:
                assert a.text.startswith("Yes") == expected["valid"]
            checked += 1
    assert checked >= 3


# -- values ------------------------------------------------------------------------------------


def test_amounts_read_with_indian_grouping_and_paise_only_when_present():
    assert format_amount(Decimal("1000000")) == "Rs 10,00,000"
    assert format_amount(Decimal("45999.0")) == "Rs 45,999"
    assert format_amount(Decimal("1234.5")) == "Rs 1,234.50"
    assert format_amount(Decimal("999")) == "Rs 999"
    assert format_amount(Decimal("12345678")) == "Rs 1,23,45,678"
    assert format_amount(Decimal("0")) == "Rs 0"


def test_dates_use_a_fixed_english_month_table(monkeypatch):
    import locale

    monkeypatch.setattr(locale, "setlocale", lambda *a, **k: "de_DE")
    assert format_date(date(2034, 3, 14)) == "14 Mar 2034"
    assert format_date(date(2025, 12, 1)) == "1 Dec 2025"
    assert [format_date(date(2026, m, 5)).split()[1] for m in range(1, 13)] == [
        "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    ]  # fmt: skip


def test_an_amount_answer_and_a_list_answer(store):
    rows = make_rows(
        store,
        DocType.health_policy,
        {"insurer": "Star", "sum_insured": 1000000.0, "insured": ["Ravi Rao", "Kavita Rao"]},
        ["Sum Insured: Rs. 10,00,000", "Insured: Ravi Rao, Kavita Rao"],
    )
    amount = compose(query(field="sum_insured"), rows, store, TODAY)
    assert amount.text == "Rs 10,00,000" and amount.value == 1000000.0
    people = compose(query(field="insured"), rows, store, TODAY)
    assert people.text == "Ravi Rao, Kavita Rao"


def test_where_bought_is_the_seller_and_city_or_the_platform_and_order_id(store):
    shop = make_rows(
        store,
        DocType.tax_invoice,
        {"seller": "Croma", "seller_location": "Bengaluru"},
        ["Croma Electronics", "Bengaluru"],
    )
    a = compose(query(field="seller"), shop, store, TODAY)
    assert (a.text, a.field, a.value) == ("Croma, Bengaluru", "seller", "Croma")
    online = make_rows(
        store,
        DocType.extended_warranty,
        {"seller": "Amazon", "seller_location": "Amazon.in", "order_id": "408-1234567-9876543"},
        ["Sold by Amazon", "Order ID 408-1234567-9876543"],
        doc_id="d2",
    )
    b = compose(query(field="seller"), online, store, TODAY)
    assert b.text == "Amazon, Amazon.in, order ID 408-1234567-9876543"


# -- locating a line ---------------------------------------------------------------------------


def test_dates_are_found_however_they_are_printed():
    for printed in (
        "Invoice Date: 18/02/2025",
        "Dated 18-Feb-2025",
        "18.02.2025",
        "18th February 2025",
        "February 18, 2025",
        "Issued 2025-02-18",
    ):
        assert locate(date(2025, 2, 18), "date", [stored_line(printed)]), printed


def test_a_different_date_is_not_located():
    assert not locate(date(2025, 2, 18), "date", [stored_line("Invoice Date: 19/02/2025")])
    assert not locate(date(2025, 2, 18), "date", [stored_line("no dates here")])


def test_a_date_value_may_be_stored_text():
    assert locate("2025-02-18", "date", [stored_line("18/02/2025")])


def test_amounts_with_indian_grouping():
    assert locate(Decimal("1000000"), "amount", [stored_line("Sum Insured: Rs. 10,00,000")])
    assert locate(1000000.0, "amount", [stored_line("Rs. 10,00,000/-")])
    assert locate(45999.5, "amount", [stored_line("Total 45,999.50")])
    assert not locate(Decimal("1000000"), "amount", [stored_line("Sum Insured: Rs. 10,000")])


def test_a_masked_identifier_line_is_cited_by_its_last_four():
    assert locate("490154203237518", "identifier", [stored_line("IMEI: XXXXXXXXXXX7518")])
    assert not locate("490154203237518", "identifier", [stored_line("IMEI: XXXXXXXXXXX7519")])
    assert not locate("490154203237518", "identifier", [stored_line("IMEI: XXXX7518")])


def test_identifiers_match_by_letters_and_digits_only():
    assert locate("p/123-45", "identifier", [stored_line("Policy No: P 123 45")])
    assert locate("ABCDE1234F", "identifier", [stored_line("PAN abcde1234f")])
    assert locate("234567891234", "aadhaar", [stored_line("XXXX XXXX 1234")])
    assert locate("234567891234", "aadhaar", [stored_line("XXXXXXXX1234")])
    assert locate("29ABCDE1234F1Z5", "gstin", [stored_line("GSTIN: 29ABCDE1234F1Z5")])


def test_names_match_by_containment_or_a_close_spelling():
    line = [stored_line("Policyholder: MRS KAVITA RAO")]
    assert locate("Kavita Rao", "name", line)
    assert locate("Kavita Rau", "name", [stored_line("KAVITA RAO")])
    assert not locate("Suresh Rao", "name", line)
    assert locate(
        "12 MG Road, Bengaluru", "address", [stored_line("Flat 4, 12 MG Road, Bengaluru")]
    )
    assert locate("Star Health", "text", [stored_line("Star Health and Allied Insurance")])


def test_a_list_is_located_item_by_item():
    lines = [stored_line("Insured: Ravi Rao", 0), stored_line("Kavita Rao", 1)]
    refs = locate(["Ravi Rao", "Kavita Rao", "Kiran Menon"], "list", lines)
    assert [(r.page, r.idx) for r in refs] == [(0, 0), (0, 1)]
    assert locate(["Nobody"], "list", lines) == []
    assert locate([], "list", lines) == []


def test_located_lines_carry_the_page_index_and_box():
    ln = stored_line("Invoice Date: 18/02/2025", idx=3, page=1)
    assert locate(date(2025, 2, 18), "date", [ln]) == [LineRef(1, 3, ln.bbox)]


# -- when there is no answer ------------------------------------------------------------------


def test_no_located_line_means_no_direct_answer(store):
    rows = make_rows(
        store,
        DocType.health_policy,
        {"insurer": "Star", "policy_number": "P/999"},
        ["Star Health", "Thank you"],
    )
    a = compose(query(field="policy_number"), rows, store, TODAY)
    assert a == NoAnswer("not_on_page", [rows[0].rel_path])


def test_find_and_list_and_a_lookup_without_a_field_show_rows_only(store):
    rows = policy_rows(store, date(2027, 3, 31))
    assert compose(query(intent="find"), rows, store, TODAY) is None
    assert compose(query(intent="list", field="end_date"), rows, store, TODAY) is None
    assert compose(query(), rows, store, TODAY) is None


def test_no_rows_is_no_documents(store):
    assert compose(query(field="end_date"), [], store, TODAY) == NoAnswer("no_documents", [])


def test_a_field_the_top_document_does_not_hold_is_no_field(store):
    rows = policy_rows(store, date(2027, 3, 31))
    assert compose(query(field="invoice_number"), rows, store, TODAY) == NoAnswer(
        "no_field", [rows[0].rel_path]
    )
    empty = make_rows(store, DocType.tax_invoice, {"seller": "Croma"}, ["Croma"], doc_id="d9")
    assert compose(query(field="invoice_number"), empty, store, TODAY).reason == "no_field"


def test_a_weak_top_row_with_no_filter_is_declined(store):
    rows = policy_rows(store, date(2027, 3, 31), score=0.0)
    a = compose(query(field="end_date"), rows, store, TODAY)
    assert a == NoAnswer("weak_match", [rows[0].rel_path])
    rows[0] = Row(**{**rows[0].__dict__, "score": answer_module.MIN_FUSED / 2})
    assert compose(query(field="end_date"), rows, store, TODAY).reason == "weak_match"


def test_a_strong_score_or_a_keyword_line_is_enough_without_a_filter(store):
    rows = policy_rows(store, date(2027, 3, 31), score=answer_module.MIN_FUSED)
    assert isinstance(compose(query(field="end_date"), rows, store, TODAY), Answer)
    rows = policy_rows(store, date(2027, 3, 31), score=0.0, doc_id="d2")
    rows[0] = Row(**{**rows[0].__dict__, "lines": [LineRef(0, 1, (0.0, 0.0, 1.0, 0.1))]})
    assert isinstance(compose(query(field="end_date"), rows, store, TODAY), Answer)


def test_a_filter_only_row_at_score_zero_is_a_real_candidate(store):
    rows = policy_rows(store, date(2027, 3, 31), score=0.0)
    for named in (
        {"people": ["p1"]},
        {"types": [DocType.health_policy]},
        {"place": "Star Health"},
        {"range": DateRange(end=date(2030, 1, 1)), "role": "expiry"},
    ):
        a = compose(query(field="end_date", **named), rows, store, TODAY)
        assert isinstance(a, Answer), named


def test_an_id_number_answer_is_marked_masked(store):
    rows = make_rows(
        store, DocType.pan, {"holder": "Ravi Rao", "number": "ABCDE1234F"}, ["PAN ABCDE1234F"]
    )
    a = compose(query(field="number", types=[DocType.pan]), rows, store, TODAY)
    assert a.masked and a.value == "ABCDE1234F" and a.text == "ABCDE1234F"
    other = policy_rows(
        store, date(2027, 3, 31), lines=["Policy No P/123", "Ends 31-Mar-2027"], doc_id="d2"
    )
    assert not compose(query(field="policy_number"), other, store, TODAY).masked


def test_a_masked_identifier_answer_cites_the_masked_line(store):
    rows = make_rows(
        store,
        DocType.warranty_card,
        {"brand": "Apple", "serial_number": "490154203237518"},
        ["IMEI: XXXXXXXXXXX7518"],
    )
    a = compose(query(field="serial_number"), rows, store, TODAY)
    assert isinstance(a, Answer) and a.page == 0 and len(a.lines) == 1


def test_an_answer_names_its_document_page_and_lines_when_the_value_is_on_page_two(store):
    add_doc(store, "d3", "health_policy", {"insurer": "Star", "policy_number": "P/123"}, ["Star"])
    rows = make_rows(
        store, DocType.health_policy, {"policy_number": "P/777"}, ["x", "Policy No P/777"],
        doc_id="d4",
    )  # fmt: skip
    a = compose(query(field="policy_number"), rows, store, TODAY)
    assert (a.document_id, a.page, [(r.page, r.idx) for r in a.lines]) == ("d4", 0, [(0, 1)])


@pytest.mark.parametrize("bad", [None, "", []])
def test_an_empty_stored_value_is_no_field(store, bad):
    rows = make_rows(store, DocType.health_policy, {"insurer": bad}, ["Star"])
    assert compose(query(field="insurer"), rows, store, TODAY).reason == "no_field"
