from datetime import date

import pytest

from evals.search_set import EVAL_TODAY, apply_query
from household_vault.doctypes import Area, DocType
from household_vault.search.dates import DateRange
from household_vault.search.index import KeywordIndex
from household_vault.search.query import Query
from household_vault.search.retrieve import Searcher, rrf
from household_vault.search.vectors import VectorIndex
from tests.conftest import add_doc


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
    assert rows and rows[0].doc_type is DocType.health_policy and "p2" in rows[0].people


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


def _add_received_date_invoice(search_world):
    """A filed invoice with no printed date: its stored date is the day it was received."""
    from household_vault.reading.lines import PageText
    from tests.conftest import item_id, line, row

    store = search_world.store
    source = next(d for d in search_world.truth.values() if d.doc_id == "tax_invoice-6-photo")
    fields = {**source.fields, "invoice_date": None}
    store.add_document(
        row(
            "received-1",
            item_id=item_id(store),
            doc_type=DocType.tax_invoice,
            area="purchases",
            owner="home",
            fields=fields,
            doc_date=date(2026, 6, 1),
            date_source="received",
        ),
        [("home", "owner"), ("p3", "linked")],
        [PageText(page=0, width=1, height=1, lines=[line("Croma tax invoice")])],
    )
    KeywordIndex(store).add("received-1")
    search_world.truth["received-1"] = source.model_copy(
        update={"doc_id": "received-1-truth", "fields": fields}
    )


@pytest.mark.parametrize(
    "fields",
    [
        dict(role="document", range=DateRange(end=date(2030, 1, 1))),
        dict(role="document", range=DateRange(start=date(2026, 5, 1), end=date(2026, 7, 1))),
        dict(range=DateRange(end=date(2030, 1, 1))),
        dict(place="croma", range=DateRange(end=date(2030, 1, 1))),
    ],
)
def test_a_received_date_is_not_a_document_date(fields, searcher, search_world):
    _add_received_date_invoice(search_world)
    q = query(intent="list", **fields)
    got = {search_world.truth[r.document_id].doc_id for r in searcher.list(q)}
    want = set(apply_query(q, list(search_world.truth.values())))
    assert got == want
    assert "received-1-truth" not in got


def test_an_unfiltered_list_shows_no_date_for_a_received_date(searcher, search_world):
    _add_received_date_invoice(search_world)
    rows = {r.document_id: r for r in searcher.list(query(intent="list", role="document"))}
    assert rows["received-1"].date is None


def _keyword_only(search_store):
    return Searcher(search_store, KeywordIndex(search_store), VectorIndex(search_store, None))


POLICIES = [DocType.health_policy, DocType.life_policy, DocType.vehicle_policy]


def test_filter_only_rows_follow_the_ranked_rows_and_never_repeat(search_store):
    rows = _keyword_only(search_store).lookup(query(types=POLICIES), "Shield")
    ranked = [r for r in rows if r.score > 0]
    padded = [r for r in rows if r.score == 0]
    assert ranked and padded and rows == ranked + padded
    assert all(r.lines == [] for r in padded)
    assert [r.doc_date for r in padded] == sorted((r.doc_date for r in padded), reverse=True)
    ids = [r.document_id for r in rows]
    assert len(ids) == len(set(ids)) == 5


def test_filter_only_rows_fill_up_to_the_limit_and_no_further(search_store):
    rows = _keyword_only(search_store).lookup(query(types=POLICIES), "Shield", limit=3)
    assert len(rows) == 3


def test_filter_only_rows_answer_when_nothing_ranks(search_store):
    rows = _keyword_only(search_store).lookup(query(types=POLICIES), "zzzznothing")
    assert len(rows) == 5 and all(r.score == 0 for r in rows)


def test_quick_never_returns_filter_only_rows(search_store):
    only = _keyword_only(search_store)
    assert only.quick("zzzznothing") == []
    assert all(r.score > 0 for r in only.quick("Croma"))


def test_a_narrow_filter_ranks_its_documents_when_a_common_word_fills_the_pool(
    search_store, monkeypatch
):
    import household_vault.search.retrieve as retrieve

    monkeypatch.setattr(retrieve, "POOL", 3)
    only = _keyword_only(search_store)
    unfiltered = {h.document_id for h in only.keyword.search("policy", limit=3, prefix_last=False)}
    wanted = {d.id for d in search_store.documents_of_type(DocType.vehicle_policy)}
    assert not wanted & unfiltered  # the pool alone would lose them
    rows = only.lookup(query(types=[DocType.vehicle_policy], words="policy"), "policy")
    mine = [r for r in rows if r.document_id in wanted]
    assert {r.document_id for r in mine} == wanted and all(r.score > 0 for r in mine)


def test_the_restriction_reaches_both_indexes(searcher, search_store):
    ids = [d.id for d in search_store.documents_of_type(DocType.vehicle_policy)]
    only = ids[:1]
    kw = searcher.keyword.search("policy", only=only, prefix_last=False)
    assert kw and {h.document_id for h in kw} == set(only)
    vec = searcher.vectors.search("policy", only=only)
    assert vec and {h.document_id for h in vec} == set(only)
    assert searcher.keyword.search("policy", only=[], prefix_last=False) == []
    assert searcher.vectors.search("policy", only=[]) == []
    assert searcher.keyword.search("policy", only=None, prefix_last=False)


def _lg_warranty(search_store):
    return next(
        d
        for d in search_store.documents_of_type(DocType.warranty_card)
        if d.fields.get("brand") == "LG"
    )


def _someone_else(search_store, doc):
    named = {p for p, _ in search_store.people_of(doc.id)}
    return next(p for p in ("p1", "p2", "p4") if p not in named)


def test_a_lookup_whose_reading_names_the_wrong_person_still_finds_the_document(
    searcher, search_store
):
    """The prompt is about the LG refrigerator warranty, but the reading put another person on
    it: the unfiltered ranking still brings the right document into the top 3."""
    doc = _lg_warranty(search_store)
    prompt = "LG refrigerator warranty card"
    assert doc.id in [r.document_id for r in searcher.quick(prompt)[:3]]
    wrong = query(
        people=[_someone_else(search_store, doc)],
        types=[DocType.warranty_card],
        words="LG refrigerator",
    )
    assert doc.id not in searcher._candidates(wrong)  # the misread filter removes it
    rows = searcher.lookup(wrong, prompt)
    assert doc.id in [r.document_id for r in rows[:3]]


def test_a_correct_reading_still_ranks_the_filtered_document_first(searcher, search_store):
    doc = _lg_warranty(search_store)
    right = query(people=["home"], types=[DocType.warranty_card], words="LG refrigerator")
    rows = searcher.lookup(right, "LG refrigerator warranty card")
    assert rows[0].document_id == doc.id


def test_a_list_keeps_its_filters_hard(searcher, search_store):
    doc = _lg_warranty(search_store)
    wrong = query(
        intent="list", people=[_someone_else(search_store, doc)], types=[DocType.warranty_card]
    )
    assert doc.id not in [r.document_id for r in searcher.list(wrong)]


def test_place_values_are_the_distinct_stored_places(store):
    from tests.conftest import add_doc

    add_doc(store, "a", "scan_report", {"hospital": "Anil Diagnostics"}, ["Scan"])
    add_doc(store, "b", "scan_report", {"hospital": "Anil Diagnostics"}, ["Scan"])
    add_doc(
        store, "c", "tax_invoice", {"seller": "Epic Electronics", "invoice_number": "A1"}, ["x"]
    )
    add_doc(store, "d", "tax_invoice", {"invoice_number": "A2"}, ["x"])
    searcher = _keyword_only(store)
    assert searcher.place_values() == {
        "Anil Diagnostics": frozenset({DocType.scan_report}),
        "Epic Electronics": frozenset({DocType.tax_invoice}),
    }


def test_quick_finds_a_natural_prompt_with_the_vectors_off(search_world):
    searcher = Searcher(
        search_world.store, KeywordIndex(search_world.store), VectorIndex(search_world.store, None)
    )
    rows = searcher.quick("Kavita health policy")
    assert rows and rows[0].doc_type is DocType.health_policy
    assert "p2" in rows[0].people
    assert searcher.quick("LG refrigerator invoice")[0].doc_type is DocType.tax_invoice


def test_an_identifier_is_found_whole_or_by_its_last_four(search_store, searcher):
    imei = "35" + "".join(str((i * 7 + 3) % 10) for i in range(13))  # synthetic, 15 digits
    add_doc(search_store, "imei-inv", "tax_invoice", {"serial_number": imei}, ["IMEI: masked"])
    KeywordIndex(search_store).add("imei-inv")
    for typed in (imei, f"•••• {imei[-4:]}", imei[-4:]):
        top3 = [r.document_id for r in searcher.quick(typed, limit=3)]
        assert "imei-inv" in top3, typed


def test_a_possessive_brand_or_insurer_is_no_person(search_store, searcher):
    from vault_synth.household import HOUSEHOLD

    from household_vault.search.query import QueryReading, resolve

    add_doc(search_store, "sam", "warranty_card", {"brand": "Samsung", "product": "Washer"}, ["x"])
    add_doc(
        search_store,
        "care",
        "health_policy",
        {"insurer": "Care Health Insurance Limited", "policy_number": "P1"},
        ["x"],
    )
    places = searcher.place_values()
    today = date(2026, 11, 21)

    def unread(prompt: str, **kw) -> list[str]:
        base = {"intent": "lookup", "people": [], "types": [], "areas": [], "field": None}
        reading = QueryReading(**{**base, "date": None, "place": None, "words": "", **kw})
        return resolve(reading, HOUSEHOLD, today, prompt, places).unread

    assert unread("What is the invoice date on Samsung's invoice?") == []
    assert unread("Find LG's invoice") == []
    assert unread("What is the policy number on Care's health policy?") == []
    assert unread("Suresh's policy number") == []
    assert unread("Meera's PAN card number") == ["person: Meera"]
