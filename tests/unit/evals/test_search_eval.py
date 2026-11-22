import json
import random
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from vault_synth.model import SynthDoc

from evals.runner import main
from evals.search_eval import (
    SMOKE_DIR,
    RecordedEmbedder,
    RecordedPromptReader,
    Result,
    SearchRow,
    declined,
    judge,
    load_smoke_questions,
    query_differences,
    run_search,
    same_value,
    smoke_documents,
    smoke_questions,
    stated_status,
    summarise_search,
)
from evals.search_set import (
    EVAL_TODAY,
    EVAL_V1,
    SET_SEED,
    Question,
    _list_drafts,
    _list_questions,
    _where,
)
from household_vault.doctypes import AREA, Area, DocType
from household_vault.leakscan import scan_outputs, scan_text
from household_vault.people import load_household
from household_vault.reading.ollama import ModelUnavailable
from household_vault.search.answer import Answer, NoAnswer
from household_vault.search.query import Query, resolve
from household_vault.search.retrieve import LineRef, Row
from tests.conftest import add_doc
from tests.fakes import FakeEmbedder, FakePromptReader

HOUSEHOLD = load_household(EVAL_V1 / "household.json")


class TruthListReader:
    """Answers every list prompt of a smoke set with the reading its truth query came from."""

    name = "truth-reader"

    def __init__(self, docs: list[SynthDoc], questions: list[Question]) -> None:
        drafts = _list_drafts(docs, HOUSEHOLD, random.Random(f"{SET_SEED}/val/list"))
        by_query = {
            resolve(d.reading, HOUSEHOLD, EVAL_TODAY).model_dump_json(): d.reading for d in drafts
        }
        self.answers: dict[str, str] = {}
        for q in questions:
            assert q.query is not None
            self.answers[q.prompt] = by_query[q.query.model_dump_json()].model_dump_json()

    def read(self, prompt: str) -> str:
        return self.answers[prompt]


@pytest.fixture(scope="module")
def smoke_docs() -> list[SynthDoc]:
    return smoke_documents()


def test_true_readings_score_perfectly_on_lists(tmp_path: Path, oracle_dir: Path, smoke_docs):
    lists = _list_questions(smoke_docs, HOUSEHOLD, "val", EVAL_TODAY, SET_SEED)[:10]
    assert len(lists) == 10
    facts: dict[str, Any] = {}
    rows = run_search(
        "val",
        TruthListReader(smoke_docs, lists),
        FakeEmbedder(),
        oracle_dir,
        tmp_path / "work",
        docs=smoke_docs,
        questions=lists,
        facts=facts,
    )
    summary = summarise_search(rows, facts)
    assert summary["list_reading"]["all"] == 1.0
    assert summary["readings_missing"] == 0
    assert summary["secrets_found"] == 0 and facts["filed"] > 10


def lookup_question(doc: SynthDoc, field: str) -> Question:
    page, box = _where(doc, field)
    return Question(
        id="val-lookup-001",
        split="val",
        kind="lookup",
        origin="eval-v1",
        style="question",
        prompt="x",
        targets=[doc.doc_id],
        field=field,
        value=doc.fields[field],
        page=page,
        box=box,
    )


def an_answer(doc_id: str, field: str, value: Any, text: str, lines: list[LineRef]) -> Answer:
    return Answer(text, field, value, doc_id, lines[0].page, lines, False)


def test_a_cited_line_on_the_wrong_page_is_not_a_correct_citation(smoke_docs):
    doc = next(d for d in smoke_docs if d.doc_id == "health_policy-1-photo")
    q = lookup_question(doc, "policy_number")
    assert q.page is not None and q.box is not None
    truth = {doc.doc_id: doc}
    back = {"db-1": doc.doc_id}
    value = doc.fields["policy_number"]

    def judged(page: int, box: tuple[float, float, float, float]) -> SearchRow:
        answer = an_answer("db-1", "policy_number", value, str(value), [LineRef(page, 0, box)])
        res = Result(Query(intent="lookup", field="policy_number"), [], answer, [])
        return judge(q, res, truth, back)

    right = judged(q.page, q.box)
    assert (right.answer_correct, right.citation_ok) == (True, True)
    wrong_page = judged(q.page + 1, q.box)
    assert (wrong_page.answer_correct, wrong_page.citation_ok) == (True, False)
    x0, y0, x1, y1 = q.box
    elsewhere = judged(q.page, (x0, y0 + 500, x1, y1 + 500))
    assert elsewhere.citation_ok is False
    other_doc = an_answer("db-2", "policy_number", value, str(value), [LineRef(q.page, 0, q.box)])
    res = Result(Query(intent="lookup", field="policy_number"), [], other_doc, [])
    assert judge(q, res, truth, back).citation_ok is False  # not one of the targets


def test_a_decline_counts_as_a_wrong_answer_and_names_its_cause(smoke_docs):
    doc = next(d for d in smoke_docs if d.doc_id == "health_policy-1-photo")
    q = lookup_question(doc, "policy_number")
    truth, back = {doc.doc_id: doc}, {"db-1": doc.doc_id}
    row_of_doc = Row(
        "db-1", doc.doc_type, "p1", ["p1"], "insurance", "x", date(2026, 1, 1), {}, None, 0.0, []
    )
    query = Query(intent="lookup", field="policy_number")
    declined_weak = Result(query, [row_of_doc], NoAnswer("weak_match", []), [])
    row = judge(q, declined_weak, truth, back)
    assert (row.answer_correct, row.answered, row.cause) == (False, False, "weak match declined")
    assert row.top1 is True and row.declined is True
    wrong_field = Result(Query(intent="lookup", field="insurer"), [row_of_doc], None, [])
    assert judge(q, wrong_field, truth, back).cause == "reading misread"
    other = Row(
        "db-9", doc.doc_type, "p1", ["p1"], "insurance", "x", date(2026, 1, 1), {}, None, 0.5, []
    )
    assert judge(q, Result(query, [other], None, []), truth, back).cause == "retrieval miss"
    off = Result(None, [], None, [])
    assert judge(q, off, truth, back).cause == "reading off"


def put_in_search_text(store, doc_id: str, text: str) -> None:
    store.conn.execute(
        "insert into search_text values (?, ?, ?, ?, ?, ?)", (doc_id, 0, 99, "line", None, text)
    )
    store.conn.commit()


def test_secrets_scan_covers_the_index_tables(store, vault, settings):
    add_doc(store, "d1", "tax_invoice", {"seller": "Croma"}, ["Paid by card"])
    assert scan_outputs(vault, settings.db_path, settings.log_dir) == []
    put_in_search_text(store, "d1", "Paid by card 4111111111111111")
    hits = scan_outputs(vault, settings.db_path, settings.log_dir)
    assert any("search_text" in h for h in hits), hits


def test_status_is_read_from_the_answer_text():
    assert stated_status("Yes, until 3 Mar 2027.") == {"valid": True}
    assert stated_status("Ended 3 Mar 2026.") == {"valid": False}
    assert stated_status("Compressor: yes, until 3 Mar 2031. Panel: ended 3 Mar 2026.") == {
        "compressor": True,
        "panel": False,
    }
    assert stated_status("12 Mar 2027") is None


def test_values_are_compared_by_the_fields_kind():
    assert same_value("date", "2027-03-04", "2027-03-04")
    assert same_value("date", "4 Mar 2027", "2027-03-04")
    assert not same_value("date", "2027-03-04", "2027-03-05")
    assert same_value("amount", "Rs 12,000", "12000")
    assert same_value("identifier", "AB 123-4", "ab1234")
    assert same_value("list", [{"part": "Panel", "years": 3}], [{"part": "panel", "years": "3.0"}])
    assert not same_value("text", "Croma", None)


def test_a_list_reads_right_when_every_slot_matches_after_area_expansion():
    want = Query(intent="list", people=["p1"], areas=[Area.insurance])
    spelled = Query(
        intent="list",
        people=["p1"],
        types=[t for t in DocType if t.value.endswith("_policy")],
    )
    expanded = Query(
        intent="list", people=["p1"], types=[t for t, a in AREA.items() if a is Area.insurance]
    )
    assert query_differences(expanded, want) == []
    assert query_differences(spelled, want) in ([], ["types"])
    assert query_differences(Query(intent="find", people=["p2"], areas=[Area.insurance]), want) == [
        "intent",
        "people",
    ]
    assert query_differences(
        Query(intent="list", people=["p1"], areas=[Area.insurance], place="Croma"), want
    ) == ["place"]


def row_with(**changes: Any) -> SearchRow:
    base: dict[str, Any] = {
        "id": "q",
        "kind": "lookup",
        "origin": "eval-v1",
        "style": "terse",
        "prompt": "p",
    }
    base.update(changes)
    return SearchRow(**base)


def test_the_summary_splits_every_metric_by_origin_and_leaves_the_cold_call_out():
    rows = [
        row_with(top1=True, top3=True, seconds_quick=9.0, seconds_full=30.0),
        row_with(top1=False, top3=True, seconds_quick=1.0, seconds_full=3.0),
        row_with(origin="extra", top1=True, top3=True, seconds_quick=2.0, seconds_full=5.0),
        row_with(origin="extra", kind="none", declined=True, seconds_quick=3.0, seconds_full=7.0),
    ]
    s = summarise_search(rows)
    assert s["top1"] == {"all": pytest.approx(2 / 3), "eval-v1": 0.5, "extra": 1.0}
    assert s["declined_when_none"] == {"all": 1.0, "eval-v1": None, "extra": 1.0}
    assert s["n"]["top1"]["all"] == 3
    assert s["seconds_quick"]["all"]["median"] == 2.0 and s["seconds_quick"]["all"]["n"] == 3
    assert s["seconds_full"]["all"]["p95"] == 7.0
    assert s["cold_first_seconds"] == {"quick": 9.0, "full": 30.0}


def test_declined_follows_the_apps_weak_evidence_rule():
    top = Row("d", DocType.pan, "p1", ["p1"], "identity", "x", date(2026, 1, 1), {}, None, 0.01, [])
    assert declined(Result(Query(intent="find"), [top], None, []))  # no filter, score under 0.02
    assert not declined(Result(Query(intent="find", people=["p1"]), [top], None, []))
    assert declined(Result(Query(intent="find"), [], None, []))
    assert declined(Result(Query(intent="find", unread=["person: Anil"]), [top], None, []))
    assert not declined(
        Result(Query(intent="find", people=["p1"], unread=["date: soon"]), [top], None, [])
    )


def test_a_recorded_prompt_reader_replays_and_a_new_reading_prompt_invalidates(tmp_path):
    live = FakePromptReader({"hello": "{}"})
    rec = RecordedPromptReader(tmp_path / "r", tmp_path / "r", live=live)
    assert rec.read("hello") == "{}" and live.calls == 1
    replay = RecordedPromptReader(tmp_path / "r")
    assert replay.read("hello") == "{}"
    with pytest.raises(ModelUnavailable):
        replay.read("other")
    replay.system = "another prompt"
    with pytest.raises(ModelUnavailable):
        replay.read("hello")
    with pytest.raises(ValueError):
        RecordedPromptReader(tmp_path, tmp_path)


def test_a_recorded_embedder_replays_float16_vectors_exactly(tmp_path):
    live = FakeEmbedder()
    rec = RecordedEmbedder(tmp_path / "v", tmp_path / "v", live=live)
    first = rec.embed_documents(["a b", "c d", "a b"])
    assert first.shape == (3, 512) and live.document_calls == 1
    query = rec.embed_query("a b")
    replay = RecordedEmbedder(tmp_path / "v", name="fake-embed")
    assert np.array_equal(replay.embed_documents(["a b", "c d", "a b"]), first)
    assert np.array_equal(replay.embed_query("a b"), query)
    with pytest.raises(ModelUnavailable):
        replay.embed_documents(["never seen"])
    with pytest.raises(ModelUnavailable):
        replay.embed_query("never seen")
    assert replay.name == "fake-embed"


def test_the_smoke_questions_are_val_lookups_and_finds_about_smoke_photos_and_ten_lists(smoke_docs):
    qs = smoke_questions(smoke_docs)
    ids = {d.doc_id for d in smoke_docs}
    assert sum(q.kind == "list" for q in qs) == 10
    about = [q for q in qs if q.kind != "list"]
    assert about and all(set(q.targets) <= ids for q in about)
    assert {q.kind for q in about} <= {"lookup", "find"}
    assert json.loads((EVAL_V1 / "smoke.json").read_text())["split"] == "val"


def copy_smoke(tmp_path: Path) -> Path:
    import shutil

    folder = tmp_path / "search-smoke"
    shutil.copytree(SMOKE_DIR, folder)
    return folder


def test_search_smoke_fails_below_its_threshold(tmp_path, capsys):
    folder = copy_smoke(tmp_path)
    for path in folder.glob("*.json"):
        body = json.loads(path.read_text())
        if "raw" in body:  # break one reading: every prompt now reads as a find with no field
            reading = json.loads(body["raw"])
            reading.update(intent="find", field=None)
            body["raw"] = json.dumps(reading)
            path.write_text(json.dumps(body))
    assert main(["smoke", "--search-recordings", str(folder)]) == 1
    out = capsys.readouterr().out
    assert "search answer_correct" in out and "below the minimum" in out


def test_search_smoke_fails_when_a_vector_recording_is_missing(tmp_path, capsys):
    folder = copy_smoke(tmp_path)
    next(folder.glob("*.npy")).unlink()
    assert main(["smoke", "--search-recordings", str(folder)]) == 1
    assert "search: " in capsys.readouterr().out


def test_search_smoke_fails_when_a_reading_is_missing(tmp_path, capsys):
    folder = copy_smoke(tmp_path)
    next(p for p in folder.glob("*.json") if p.name != "questions.jsonl").unlink()
    assert main(["smoke", "--search-recordings", str(folder)]) == 1
    assert "readings_missing" in capsys.readouterr().out


def test_the_committed_smoke_recordings_hold_no_real_shaped_number():
    texts = [p.read_text() for p in SMOKE_DIR.glob("*.json*")]
    assert len(texts) > 20
    for text in texts:
        assert scan_text(text, allow_test_cards=True) == []


def test_the_committed_smoke_questions_are_what_the_builder_makes(smoke_docs):
    assert load_smoke_questions() == smoke_questions(smoke_docs)
