import logging
import re

import pytest

from household_vault.db import Store, migrate
from household_vault.reasons import Reason
from household_vault.search.index import KeywordIndex
from tests.conftest import add_doc, item_id


def index_texts(store: Store) -> list[str]:
    return [r[0] for r in store.conn.execute("select text from search_text")]


def test_a_version_1_database_migrates_and_its_documents_are_searchable(v1_database):
    store = Store(v1_database)  # holds one Croma invoice, "d1"
    assert migrate(store.conn) == 2
    assert KeywordIndex(store).search("Croma")[0].document_id == "d1"
    assert store.conn.execute("select count(*) from vectors").fetchone()[0] == 0
    assert migrate(store.conn) == 2


def test_a_failed_upgrade_leaves_the_version_1_database_as_it_was(v1_database, monkeypatch):
    import household_vault.search.index as index

    def boom(self, doc_id):
        raise RuntimeError("stop")

    monkeypatch.setattr(index.KeywordIndex, "add", boom)
    with pytest.raises(RuntimeError):
        migrate(v1_database)
    version = v1_database.execute("select value from meta where key = 'schema_version'")
    assert version.fetchone()[0] == "1"
    assert (
        v1_database.execute("select 1 from sqlite_master where name = 'vectors'").fetchone() is None
    )


def test_a_new_database_has_both_tables(store):
    names = {r[0] for r in store.conn.execute("select name from sqlite_master")}
    assert {"search_text", "vectors"} <= names


def test_keyword_search_treats_operators_as_words(keyword):  # Review Focus 11
    for text in [
        '"',
        "*",
        "AND",
        "NEAR(",
        "-",
        "x" * 2000,
        "policy OR 1=1",
        "\U0001f642",
        "",
        "a\x00b",
        "a\x07b",
    ]:
        keyword.search(text)  # never raises
    assert keyword.search("   ") == []


def test_operator_words_match_as_plain_words(keyword, store):
    add_doc(store, "d1", "tax_invoice", {"seller": "Croma"}, ["Paid AND delivered"])
    add_doc(store, "d2", "tax_invoice", {"seller": "Reliance"}, ["Paid on delivery"])
    keyword.add("d1")
    keyword.add("d2")
    assert [h.document_id for h in keyword.search("AND delivered")] == ["d1"]
    assert keyword.search('say "hi"') == []


def test_the_last_word_matches_as_a_prefix(keyword, store):
    add_doc(store, "d1", "tax_invoice", {"seller": "Croma"}, ["Croma"])
    keyword.add("d1")
    assert {h.document_id for h in keyword.search("crom")} == {"d1"}
    assert keyword.search("crom", prefix_last=False) == []


def test_only_the_last_word_is_a_prefix(keyword, store):
    add_doc(store, "d1", "tax_invoice", {}, ["Croma store"])
    keyword.add("d1")
    assert keyword.search("croma sto") != []
    assert keyword.search("crom store") == []


def test_line_hits_carry_the_page_and_line(keyword, store):
    add_doc(store, "d1", "tax_invoice", {}, ["first line", "second line about Voltas"])
    keyword.add("d1")
    hit = keyword.search("voltas")[0]
    assert (hit.kind, hit.page, hit.idx, hit.field) == ("line", 0, 1, None)


def test_identifiers_in_fields_are_found_when_the_line_is_masked(keyword, store):
    imei = "490154203237518"  # the published example IMEI
    add_doc(store, "inv", "tax_invoice", {"serial_number": imei}, ["IMEI: XXXXXXXXXXX7518"])
    keyword.add("inv")
    hit = keyword.search(imei)[0]
    assert hit.field == "serial_number" and hit.kind == "field" and hit.page is None


def test_dates_and_amounts_are_findable_in_the_forms_people_type(keyword, store):
    fields = {"seller": "Croma", "invoice_date": "2034-03-14", "amount": 45999.0}
    add_doc(store, "inv", "tax_invoice", fields, ["x"])
    keyword.add("inv")
    assert keyword.search("14 Mar 2034")[0].field == "invoice_date"
    assert keyword.search("2034-03-14")[0].field == "invoice_date"
    assert keyword.search("45999")[0].field == "amount"
    assert keyword.search("invoice date")[0].document_id == "inv"


def test_list_items_are_indexed(keyword, store):
    add_doc(store, "rx", "prescription", {"medicines": ["Metformin 500", "Atorvastatin"]}, ["x"])
    keyword.add("rx")
    assert keyword.search("atorvastatin")[0].field == "medicines"


def test_best_match_comes_first_and_the_limit_applies(keyword, store):
    add_doc(store, "a", "tax_invoice", {}, ["fan"])
    add_doc(store, "b", "tax_invoice", {}, ["fan fan fan"])
    keyword.add("a")
    keyword.add("b")
    hits = keyword.search("fan")
    assert hits[0].document_id == "b" and hits[0].score >= hits[1].score
    assert len(keyword.search("fan", limit=1)) == 1


def test_add_twice_and_remove(keyword, store):
    add_doc(store, "a", "tax_invoice", {"seller": "Croma"}, ["Croma"])
    keyword.add("a")
    keyword.add("a")
    assert len(index_texts(store)) == 2
    keyword.remove("a")
    assert keyword.search("croma") == [] and index_texts(store) == []


def test_rebuild_indexes_every_document_and_returns_how_many(keyword, store):
    add_doc(store, "a", "tax_invoice", {"seller": "Croma"}, ["Croma"])
    add_doc(store, "b", "tax_invoice", {"seller": "Voltas"}, ["Voltas"])
    keyword.add("a")
    assert keyword.rebuild() == 2
    assert keyword.rebuild() == 2
    assert {h.document_id for h in keyword.search("voltas")} == {"b"}
    assert (
        store.conn.execute("select count(distinct document_id) from search_text").fetchone()[0] == 2
    )


def test_undo_and_refile_update_search(filed_vault):  # Review Focus 12
    doc = filed_vault.file("tax_invoice-1-clean")
    assert KeywordIndex(filed_vault.store).search("Croma") != []
    filed_vault.undo(doc.id)
    assert KeywordIndex(filed_vault.store).search("Croma") == []


def test_a_refiled_document_is_searchable_once_at_its_new_path(filed_vault):
    w = filed_vault.world
    first = filed_vault.file("tax_invoice-1-clean")
    item = w.filer.undo(first.id)
    assert KeywordIndex(filed_vault.store).search("Croma") == []
    w.actions.retry(item.id)
    w.drain()
    refiled = filed_vault.store.item(item.id)
    assert refiled.state == "filed" and refiled.document_id is not None
    again = filed_vault.store.document(refiled.document_id)
    hits = KeywordIndex(filed_vault.store).search("Croma")
    assert hits and {h.document_id for h in hits} == {again.id}
    lines = filed_vault.store.conn.execute(
        "select count(*) from search_text where document_id = ? and kind = 'line'", (again.id,)
    ).fetchone()[0]
    assert lines == len(filed_vault.store.lines_of(again.id))


def test_filing_indexes_the_document(filed_vault):
    doc = filed_vault.file("tax_invoice-1-clean")
    hits = KeywordIndex(filed_vault.store).search("invoice")
    assert doc.id in {h.document_id for h in hits}


def test_card_documents_put_no_long_digit_run_in_the_index(filed_vault):
    filed_vault.file("card_statement-1-clean")
    texts = index_texts(filed_vault.store)
    assert texts
    assert not re.search(r"\d{13,19}", " ".join(texts))


def test_an_unknown_reason_does_not_break_loading(store, caplog):
    i = item_id(store)
    store.conn.execute(
        "update items set reasons = ? where id = ?",
        ('["no_longer_a_reason", "person_unknown"]', i),
    )
    with caplog.at_level(logging.WARNING):
        item = store.item(i)
    assert item.reasons == [Reason.person_unknown]
    assert "no_longer_a_reason" in caplog.text


def _spread(keyword, store):
    add_doc(store, "d1", "tax_invoice", {"seller": "Croma"}, ["LG Refrigerator", "Tax invoice"])
    add_doc(store, "d2", "tax_invoice", {"seller": "Reliance"}, ["Samsung Television"])
    add_doc(store, "d3", "tax_invoice", {"seller": "Croma"}, ["LG Washing Machine"])
    for d in ("d1", "d2", "d3"):
        keyword.add(d)


def test_all_words_must_share_a_line_unless_any_word_is_asked_for(keyword, store):
    _spread(keyword, store)
    assert keyword.search("Croma refrigerator invoice") == []
    ids = [h.document_id for h in keyword.search("Croma refrigerator invoice", any_word=True)]
    assert ids[0] == "d1" and set(ids) == {"d1", "d3"}


def test_any_word_ranks_documents_by_the_words_they_match_in_all_their_lines(keyword, store):
    _spread(keyword, store)
    ids = [h.document_id for h in keyword.search("LG refrigerator", any_word=True)]
    assert ids == ["d1", "d3"]  # d1 matches both words, d3 only one


def test_any_word_groups_the_hits_of_a_document_together(keyword, store):
    _spread(keyword, store)
    ids = [h.document_id for h in keyword.search("croma lg invoice", any_word=True)]
    assert ids == ["d1", "d1", "d1", "d3", "d3"]  # best document first, its hits together


def test_any_word_drops_filler_words_but_keeps_a_prompt_of_only_filler(keyword, store):
    _spread(keyword, store)
    assert [h.document_id for h in keyword.search("what is the Samsung", any_word=True)] == ["d2"]
    assert keyword.search("what is the", any_word=True) == []


def test_any_word_keeps_the_prefix_and_never_raises(keyword, store):
    _spread(keyword, store)
    assert {h.document_id for h in keyword.search("refrig", any_word=True)} == {"d1"}
    assert keyword.search("refrig", any_word=True, prefix_last=False) == []
    for text in ['"', "AND OR NEAR(", "-", "x" * 2000, "a\x00b", ""]:
        keyword.search(text, any_word=True)


def test_any_word_respects_only(keyword, store):
    _spread(keyword, store)
    hits = keyword.search("LG", any_word=True, only={"d3"})
    assert {h.document_id for h in hits} == {"d3"}


def test_the_last_four_token_adds_no_longer_digit_run(keyword, store):
    from household_vault.leakscan import scan_text

    add_doc(store, "inv", "tax_invoice", {"serial_number": "490154203237518"}, ["x"])
    keyword.add("inv")
    text = next(t for t in index_texts(store) if "serial number" in t)
    assert text.endswith("; 7518")
    # the IMEI itself is a 15-digit run; the token must not lengthen it into a 19-digit one
    assert scan_text(text, allow_test_cards=False) == scan_text(
        "serial number 490154203237518", allow_test_cards=False
    )
