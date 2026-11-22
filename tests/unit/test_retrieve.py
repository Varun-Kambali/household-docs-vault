from datetime import date

import pytest

from evals.search_set import EVAL_TODAY, apply_query
from household_vault.doctypes import Area, DocType
from household_vault.search.dates import DateRange
from household_vault.search.index import KeywordIndex
from household_vault.search.query import Query
from household_vault.search.retrieve import Searcher, rrf
from household_vault.search.vectors import VectorIndex


def query(**fields) -> Query:
    return Query(**{"intent": "lookup", **fields})


def test_rrf_rewards_agreement():
    assert rrf([["a", "b"], ["b", "c"]])[0][0] == "b"


def test_rrf_scores_by_rank_and_keeps_every_document_once():
    out = rrf([["a", "b"], ["a"]], k=10)
    assert [d for d, _ in out] == ["a", "b"]
    assert out[0][1] == pytest.approx(2 / 11) and out[1][1] == pytest.approx(1 / 12)
    assert rrf([]) == []


def test_filters_keep_the_person_owner_or_linked_and_the_type(search_store, searcher):
    rows = searcher.lookup(query(people=["p2"], types=[DocType.health_policy]), "Kavita health")
    assert rows and all(r.doc_type is DocType.health_policy and "p2" in r.people for r in rows)


def test_a_person_filter_matches_the_owner_too(searcher):
    rows = searcher.list(query(intent="list", people=["p4"], types=[DocType.health_policy]))
    assert rows and all(r.owner == "p4" for r in rows)


def test_lists_sort_by_the_role_date_inside_the_range(searcher):
    rows = searcher.list(
        query(
            intent="list",
            role="expiry",
            range=DateRange(start=EVAL_TODAY, end=date(2027, 12, 31)),
        )
    )
    dates = [r.date for r in rows]
    assert rows and dates == sorted(dates)
    assert all(EVAL_TODAY <= d <= date(2027, 12, 31) for d in dates)


def test_a_document_with_no_value_for_the_field_is_left_out_of_a_filtered_list(searcher):
    rows = searcher.list(query(intent="list", role="expiry", range=DateRange(end=date(2030, 1, 1))))
    assert rows and DocType.tax_invoice not in {r.doc_type for r in rows}


def test_an_unfiltered_list_puts_rows_without_the_date_last(searcher):
    rows = searcher.list(query(intent="list", role="expiry"))
    dates = [r.date for r in rows]
    assert None in dates and DocType.tax_invoice in {r.doc_type for r in rows}
    seen_none = False
    for d in dates:
        seen_none = seen_none or d is None
        assert d is None or not seen_none
    dated = [d for d in dates if d is not None]
    assert dated == sorted(dated)


def test_the_range_cuts_policies_beyond_it(searcher):
    inside = searcher.list(
        query(intent="list", role="expiry", range=DateRange(end=date(2027, 3, 1)))
    )
    everything = searcher.list(query(intent="list", role="expiry"))
    assert 0 < len(inside) < len([r for r in everything if r.date is not None])
    assert all(r.date <= date(2027, 3, 1) for r in inside)


def test_quick_finds_a_number_typed_in_part(searcher, invoice_number):
    assert searcher.quick(invoice_number[:-2])[0].doc_type is DocType.tax_invoice


def test_a_meaning_only_match_still_ranks(searcher):  # the invoice prints "Refrigerator"
    assert searcher.keyword.search("fridge") == []
    assert searcher.quick("fridge")[0].doc_type in (DocType.tax_invoice, DocType.warranty_card)


def test_the_place_filter_matches_the_seller(searcher, search_store):
    rows = searcher.list(query(intent="list", place="croma"))
    sellers = [search_store.document(r.document_id).fields.get("seller") for r in rows]
    assert sellers and set(sellers) == {"Croma"}


def test_list_words_must_match_by_keyword(searcher):
    rows = searcher.list(query(intent="list", words="refrigerator"))
    assert {r.doc_type for r in rows} == {DocType.tax_invoice, DocType.warranty_card}


def test_rows_carry_matched_lines_with_boxes_and_the_key_fields(searcher, search_store):
    row = searcher.quick("Croma")[0]
    assert row.lines
    stored = {(ln.page, ln.idx): ln.bbox for ln in search_store.lines_of(row.document_id)}
    assert all(stored[(ln.page, ln.idx)] == ln.bbox for ln in row.lines)
    doc = search_store.document(row.document_id)
    assert row.rel_path == doc.rel_path and row.doc_date == doc.doc_date and row.area == doc.area
    assert set(row.key_fields) <= set(doc.fields)


def test_one_row_per_document(searcher):
    rows = searcher.quick("Croma refrigerator")
    ids = [r.document_id for r in rows]
    assert len(ids) == len(set(ids))


def test_retrieval_runs_on_keywords_when_vectors_are_off(search_store):
    off = Searcher(search_store, KeywordIndex(search_store), VectorIndex(search_store, None))
    assert off.quick("Croma")[0].doc_type is DocType.tax_invoice
    assert off.quick("fridge") == []
    assert off.lookup(query(types=[DocType.health_policy]), "my policy")


def test_the_prompt_ranks_when_the_query_has_no_words(searcher):
    rows = searcher.lookup(query(types=[DocType.warranty_card]), "refrigerator warranty")
    assert rows[0].doc_type is DocType.warranty_card
    assert "refrigerator" in str(rows[0].key_fields).lower()


QUERIES = [
    dict(people=["p2"]),
    dict(people=["p4"]),
    dict(people=["home"]),
    dict(types=[DocType.health_policy]),
    dict(areas=[Area.insurance]),
    dict(types=[DocType.tax_invoice], areas=[Area.insurance]),
    dict(place="croma"),
    dict(place="LG"),
    dict(place="star health"),
    dict(role="expiry", range=DateRange(start=EVAL_TODAY, end=date(2027, 5, 1))),
    dict(role="expiry", range=DateRange(start=date(2027, 6, 1))),
    dict(role="document", range=DateRange(end=date(2025, 12, 31))),
    dict(range=DateRange(end=date(2030, 1, 1))),
    dict(role="purchase", range=DateRange(end=date(2030, 1, 1))),
    dict(
        people=["p1"],
        types=[DocType.health_policy],
        role="expiry",
        range=DateRange(end=date(2030, 1, 1)),
    ),
]


@pytest.mark.parametrize("fields", QUERIES)
def test_list_filters_mean_what_the_eval_truth_means(fields, searcher, search_world):
    q = query(intent="list", **fields)
    got = {search_world.truth[r.document_id].doc_id for r in searcher.list(q)}
    want = set(apply_query(q, list(search_world.truth.values())))
    assert got == want


def test_the_filter_parity_set_is_not_all_empty(searcher, search_world):
    sizes = []
    for fields in QUERIES:
        q = query(intent="list", **fields)
        sizes.append(len(apply_query(q, list(search_world.truth.values()))))
    assert sum(1 for s in sizes if s) >= 10
    assert len(set(sizes)) >= 4
