import json
import random
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from vault_synth.model import SynthDoc

from evals.runner import _parser, _query_model, main, results_folder
from evals.search_eval import (
    SMOKE_DIR,
    RecordedEmbedder,
    RecordedPromptReader,
    RecordingMismatch,
    Result,
    SearchRow,
    _build,
    declined,
    judge,
    load_questions,
    load_smoke_questions,
    query_differences,
    run_search,
    same_value,
    seen_in_val,
    smoke_documents,
    smoke_questions,
    stated_status,
    summarise_search,
    write_smoke_questions,
)
from evals.search_set import (
    EVAL_TODAY,
    EVAL_V1,
    SET_SEED,
    Question,
    _list_drafts,
    _list_questions,
    _where,
    wants_status,
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


def test_declined_is_what_the_app_returns(store):
    """The eval reads the route's outcome, so it cannot drift from the screen."""
    from household_vault.search.answer import compose
    from tests.conftest import add_doc

    add_doc(store, "d1", "pan", {"name": "A", "number": "ABCDE1234F"}, ["PAN"], owner="p1")
    doc = store.document("d1")
    top = Row(
        "d1", doc.doc_type, "p1", ["p1"], doc.area, doc.rel_path, doc.doc_date, {}, None, 0.01, []
    )
    solid = Row(**{**top.__dict__, "score": 0.05})
    today = date(2026, 11, 20)
    cases = [
        (Query(intent="find"), [top], True),  # no filter, score under 0.02
        (Query(intent="find", people=["p1"]), [top], False),
        (Query(intent="find"), [], True),
        (Query(intent="find", people=["p1"], words="inverter"), [top], True),
        (Query(intent="find", people=["p1"], words="inverter"), [solid], True),
        (Query(intent="find", unread=["person: Anil"]), [solid], True),
        (Query(intent="find", people=["p1"], unread=["date: soon"]), [solid], False),
        (Query(intent="find", people=["p2"]), [solid], True),  # nobody fits
        (Query(intent="lookup", field="number", people=["p2"]), [solid], True),
        (Query(intent="list", unread=["person: Anil"]), [solid], True),
        (Query(intent="list", people=["p1"]), [solid], False),
    ]
    for q, rows, want in cases:
        outcome = compose(q, rows, store, today)
        assert declined(Result(q, rows, outcome, [])) is want, q
        if q.intent != "list":
            assert (isinstance(outcome, NoAnswer) or not rows) is want


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


def test_the_smoke_questions_are_lookups_finds_nones_and_ten_lists_about_smoke_photos(smoke_docs):
    qs = smoke_questions(smoke_docs)
    ids = {d.doc_id for d in smoke_docs}
    assert sum(q.kind == "list" for q in qs) == 10
    about = [q for q in qs if q.kind not in ("list", "none")]
    assert about and all(set(q.targets) <= ids for q in about)
    assert {q.kind for q in about} <= {"lookup", "find"}
    nones = [q for q in qs if q.kind == "none"]
    val_nones = {q.id: q for q in load_questions("val") if q.kind == "none"}
    assert nones and all(val_nones[q.id] == q and not q.targets for q in nones)  # none are new
    assert json.loads((EVAL_V1 / "smoke.json").read_text())["split"] == "val"


def copy_smoke(tmp_path: Path) -> Path:
    import shutil

    tmp_path.mkdir(parents=True, exist_ok=True)
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
    next(folder.glob("*.npy")).unlink()  # a document or a query vector, whichever lists first
    assert main(["smoke", "--search-recordings", str(folder)]) == 1
    assert "search" in capsys.readouterr().out


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


def test_the_committed_smoke_questions_are_what_the_builder_makes(tmp_path):
    write_smoke_questions(tmp_path)
    committed = (SMOKE_DIR / "questions.jsonl").read_bytes()
    assert committed == (tmp_path / "questions.jsonl").read_bytes()


# -- fix round 1 ----------------------------------------------------------------------------------


def status_question(doc: SynthDoc, field: str) -> Question:
    from evals.search_set import status_of

    q = lookup_question(doc, field)
    asked = "Is it still valid?"  # only a status question wants the status in the answer
    return q.model_copy(update={"status": status_of(doc, field), "prompt": asked})


def judged_answer(q: Question, doc: SynthDoc, value: Any, text: str) -> SearchRow:
    page, box = _where(doc, q.field)
    answer = an_answer("db-1", q.field, value, text, [LineRef(page, 0, box)])
    top = Row(
        "db-1", doc.doc_type, "p1", ["p1"], "insurance", "x", date(2026, 1, 1), {}, None, 0.5, []
    )
    res = Result(Query(intent="lookup", field=q.field), [top], answer, [])
    return judge(q, res, {doc.doc_id: doc}, {"db-1": doc.doc_id})


def test_a_wrong_value_is_a_wrong_answer(smoke_docs):
    doc = next(d for d in smoke_docs if d.doc_id == "health_policy-1-photo")
    q = lookup_question(doc, "policy_number")
    right = judged_answer(q, doc, doc.fields["policy_number"], "x")
    wrong = judged_answer(q, doc, str(doc.fields["policy_number"]) + "9", "x")
    assert (right.answer_correct, wrong.answer_correct) == (True, False)
    assert wrong.cause == "wrong value"


def test_a_validity_answer_must_state_the_right_status(smoke_docs):
    doc = next(d for d in smoke_docs if d.doc_id == "vehicle_policy-1-photo")
    q = status_question(doc, "end_date")
    assert q.status is not None
    valid = q.status["valid"]
    said = {True: "Yes, until 3 Mar 2027.", False: "Ended 3 Mar 2026."}
    value = doc.fields["end_date"]
    assert judged_answer(q, doc, value, said[valid]).answer_correct is True
    assert judged_answer(q, doc, value, said[not valid]).answer_correct is False


def test_a_warranty_answer_must_state_every_part_right(smoke_docs):
    doc = next(d for d in smoke_docs if d.doc_id == "warranty_card-1-photo")
    q = status_question(doc, "warranty_parts")
    assert q.status
    value = doc.fields["warranty_parts"]

    def text(flip: bool) -> str:
        return " ".join(
            f"{name}: " + ("yes, until 3 Mar 2031." if ok != flip else "ended 3 Mar 2020.")
            for name, ok in q.status.items()
        )

    assert judged_answer(q, doc, value, text(False)).answer_correct is True
    assert judged_answer(q, doc, value, text(True)).answer_correct is False


def test_held_copies_are_exactly_the_four_variants_of_filed_photos(tmp_path, smoke_docs):
    state, ids, entries = _build(
        smoke_docs,
        EVAL_V1.parent.parent / "recordings" / "eval-v1" / "smoke",
        tmp_path,
        RecordedEmbedder(SMOKE_DIR),
    )
    try:
        held = {
            e.doc.doc_id
            for e in entries
            for i in state.store.items(["asked"])
            if i.sha256 == e.key and "possible_copy" in [r.value for r in i.reasons]
        }
        unfiled = {e.doc.doc_id for e in entries if not e.doc.expected_ask} - set(ids)
    finally:
        state.store.conn.close()
    expected = {
        "health_policy-1-clean",
        "tax_invoice-1-scan",
        "aadhaar-1-scan",
        "card_statement-1-locked",
    }
    assert held == expected and unfiled == expected


def test_a_folder_made_by_another_model_is_refused(tmp_path):
    live = FakePromptReader({"hello": "{}"})
    RecordedPromptReader(tmp_path, tmp_path, live=live, model="qwen3:4b", digest="aaa")
    RecordedEmbedder(tmp_path, tmp_path, live=FakeEmbedder(), model="emb", digest="bbb")
    assert RecordedPromptReader(tmp_path, expect="qwen3:4b").name
    assert RecordedEmbedder(tmp_path, expect="emb").name == "emb"
    with pytest.raises(RecordingMismatch):
        RecordedPromptReader(tmp_path, expect="qwen3:1.7b")
    with pytest.raises(RecordingMismatch):
        RecordedEmbedder(tmp_path, expect="other-embed")
    with pytest.raises(RecordingMismatch):
        RecordedPromptReader(tmp_path, expect="qwen3:4b", expect_digest="zzz")
    with pytest.raises(RecordingMismatch):  # recording again over another model's folder
        RecordedPromptReader(tmp_path, tmp_path, live=live, model="qwen3:1.7b")
    with pytest.raises(RecordingMismatch):  # no manifest at all
        RecordedPromptReader(tmp_path / "empty", expect="qwen3:4b")


def test_the_smoke_fails_when_the_recordings_are_from_another_model(tmp_path, capsys):
    folder = copy_smoke(tmp_path)
    manifest = json.loads((folder / "manifest.json").read_text())
    manifest["embedder"]["model"] = "some-other-embedding-model"
    (folder / "manifest.json").write_text(json.dumps(manifest))
    assert main(["smoke", "--search-recordings", str(folder)]) == 1
    assert "some-other-embedding-model" in capsys.readouterr().out


def test_missing_query_vectors_are_counted_and_fail_the_smoke(tmp_path, capsys):
    embedder = RecordedEmbedder(tmp_path, name="x")
    with pytest.raises(ModelUnavailable):
        embedder.embed_query("never recorded")
    assert embedder.missing_queries == 1
    folder = copy_smoke(tmp_path / "s")
    q = load_smoke_questions(folder)[0]
    from evals.search_eval import _sha
    from household_vault.search.vectors import QUERY_TASK

    (folder / f"{_sha(f'{QUERY_TASK}' + chr(10) + q.prompt)}.npy").unlink()
    assert main(["smoke", "--search-recordings", str(folder)]) == 1
    assert "vectors_missing" in capsys.readouterr().out


def test_damaged_recordings_count_as_missing(tmp_path):
    reader = RecordedPromptReader(tmp_path)
    from evals.search_eval import _sha

    for body in (json.dumps({"system_sha256": reader.system}), "[1]", '{"raw": 5}', "{"):
        (tmp_path / f"{_sha('p')}.json").write_text(body)
        with pytest.raises(ModelUnavailable):
            reader.read("p")
    embedder = RecordedEmbedder(tmp_path, name="x")
    from household_vault.search.vectors import QUERY_TASK

    (tmp_path / f"{_sha(QUERY_TASK + chr(10) + 'p')}.npy").write_bytes(b"\x93NUMPY")
    with pytest.raises(ModelUnavailable):
        embedder.embed_query("p")


def test_val_results_never_default_to_the_committed_folder():
    assert results_folder("val").parts[-2:] == ("var", "results-val")
    assert results_folder("test").parts[-2:] == ("evals", "results")
    args = _parser().parse_args(["search", "--split", "val", "--recordings", "r", "--replay", "x"])
    assert args.results is None


def _replay_args(folder: Path, results: Path) -> list[str]:
    reading = str(EVAL_V1.parent.parent / "recordings" / "eval-v1" / "smoke")
    return [
        "search", "--split", "val", "--smoke", "--recordings", reading,
        "--replay", str(folder), "--results", str(results),
    ]  # fmt: skip


def test_a_replay_refuses_a_model_that_was_pulled_again(tmp_path, monkeypatch, capsys):
    from evals import runner

    folder = copy_smoke(tmp_path)
    manifest = json.loads((folder / "manifest.json").read_text())
    tags = {name: body["digest"] for name, body in (
        (manifest[r]["model"], manifest[r]) for r in ("prompt_reader", "embedder")
    )}  # fmt: skip
    monkeypatch.setattr(runner.OllamaClient, "tags", lambda self: dict(tags))
    assert main(_replay_args(folder, tmp_path / "ok")) == 0
    for name in tags:
        monkeypatch.setattr(
            runner.OllamaClient, "tags", lambda self, n=name: {**tags, n: "another-digest"}
        )
        assert main(_replay_args(folder, tmp_path / "bad")) == 1
        assert "pulled again" in capsys.readouterr().out

    # Ollama off: the manifest alone is checked, as in CI
    def off(self):
        raise ModelUnavailable("off")

    monkeypatch.setattr(runner.OllamaClient, "tags", off)
    assert main(_replay_args(folder, tmp_path / "off")) == 0


def test_two_builds_of_one_vault_give_the_same_document_ids(tmp_path, smoke_docs):
    recordings = EVAL_V1.parent.parent / "recordings" / "eval-v1" / "smoke"
    found = []
    for n in range(2):
        state, _, _ = _build(smoke_docs, recordings, tmp_path / str(n), RecordedEmbedder(SMOKE_DIR))
        try:
            rows = state.store.conn.execute("select id from documents order by id")
            found.append([r[0] for r in rows])
        finally:
            state.store.conn.close()
    assert found[0] == found[1] and found[0]


def test_a_reader_replays_recordings_made_under_the_reading_prompt_it_is_given(tmp_path):
    from household_vault.search.query import PROMPT_READ, PROMPT_READ_V1

    live = FakePromptReader({"hello": "{}"})
    old = RecordedPromptReader(tmp_path, tmp_path, live=live, system=PROMPT_READ_V1)
    assert old.read("hello") == "{}"
    assert RecordedPromptReader(tmp_path, system=PROMPT_READ_V1).read("hello") == "{}"
    with pytest.raises(ModelUnavailable):  # the current prompt is not the one it was made under
        RecordedPromptReader(tmp_path).read("hello")
    assert (
        RecordedPromptReader(tmp_path).system
        == RecordedPromptReader(tmp_path, system=PROMPT_READ).system
    )


def test_the_search_runner_names_a_reading_prompt_version():
    args = _parser().parse_args(
        ["search", "--split", "val", "--recordings", "r", "--replay", "x", "--prompt", "v1"]
    )
    assert args.prompt == "v1"
    default = _parser().parse_args(
        ["search", "--split", "val", "--recordings", "r", "--replay", "x"]
    )
    assert default.prompt == "v2"


def test_the_summary_totals_the_backstop_conflicts():
    rows = [row_with(backstop_conflicts=2), row_with(), row_with(backstop_conflicts=1)]
    assert summarise_search(rows)["backstop_conflicts"] == 3


def test_the_search_runner_takes_the_reading_model_from_a_switch_or_the_config():
    base = ["search", "--split", "val", "--recordings", "r", "--replay", "x"]
    default = _parser().parse_args(base)
    named = _parser().parse_args([*base, "--query-model", "qwen3:8b"])
    assert _query_model(default, "qwen3:4b") == "qwen3:4b"
    assert _query_model(named, "qwen3:4b") == "qwen3:8b"


def test_an_unknown_person_decline_names_its_cause(smoke_docs):
    doc = next(d for d in smoke_docs if d.doc_id == "health_policy-1-photo")
    q = lookup_question(doc, "policy_number")
    truth, back = {doc.doc_id: doc}, {"db-1": doc.doc_id}
    row_of_doc = Row(
        "db-1", doc.doc_type, "p1", ["p1"], "insurance", "x", date(2026, 1, 1), {}, None, 0.0, []
    )
    query = Query(intent="lookup", field="policy_number", unread=["person: Anil"])
    res = Result(query, [row_of_doc], NoAnswer("unknown_person", []), [])
    row = judge(q, res, truth, back)
    assert (row.answered, row.declined, row.cause) == (False, True, "unknown person")


def test_the_api_carries_the_unknown_person_reason():
    from household_vault.api.models import NoAnswerOut

    assert NoAnswerOut(reason="unknown_person", closest=[]).reason == "unknown_person"


def test_the_keyword_only_quick_search_is_judged_apart(smoke_docs):
    doc = next(d for d in smoke_docs if d.doc_id == "health_policy-1-photo")
    q = lookup_question(doc, "policy_number")
    truth, back = {doc.doc_id: doc}, {"db-1": doc.doc_id}
    hit = Row(
        "db-1", doc.doc_type, "p1", ["p1"], "insurance", "x", date(2026, 1, 1), {}, None, 0.1, []
    )
    miss = Row(**{**hit.__dict__, "document_id": "db-2"})
    res = Result(Query(intent="lookup"), [hit], None, [], quick_off=[miss, miss, hit])
    row = judge(q, res, truth, back)
    assert (row.quick_off_top1, row.quick_off_top3) == (False, True)
    nothing = judge(q, Result(Query(intent="lookup"), [hit], None, []), truth, back)
    assert (nothing.quick_off_top1, nothing.quick_off_top3) == (None, None)
    rows = [row, row]
    s = summarise_search(rows)
    assert s["quick_off_top3"]["all"] == 1.0 and s["quick_off_top1"]["all"] == 0.0


def test_a_replay_result_names_the_digests_of_its_recordings_manifest(tmp_path):
    folder = copy_smoke(tmp_path)
    manifest = json.loads((folder / "manifest.json").read_text())
    assert main(_replay_args(folder, tmp_path / "out")) == 0
    (result,) = (tmp_path / "out").glob("*.json")
    models = json.loads(result.read_text())["models"]
    want = {manifest[r]["model"]: manifest[r]["digest"] for r in ("prompt_reader", "embedder")}
    assert models["live"] is False and models["digests"] == want


def test_test_questions_that_also_stand_in_val_are_reported_apart():
    val = load_questions("val")[0]
    twin = SearchRow("test-x", "find", "extra", "terse", val.prompt.upper() + " ", top1=True)
    fresh = SearchRow("test-y", "find", "extra", "terse", "a prompt only test has", top1=False)
    report = seen_in_val([twin, fresh], "test")
    assert report is not None
    assert report["ids"] == ["test-x"] and report["n"] == 1 and report["top1"] == 1.0
    assert seen_in_val([twin], "val") is None


def test_five_test_prompts_are_in_val_verbatim():
    """What the Task 37 review found, now found by code (ADR 0021 notes it)."""
    rows = [SearchRow(q.id, q.kind, q.origin, q.style, q.prompt) for q in load_questions("test")]
    report = seen_in_val(rows, "test")
    assert report is not None and report["n"] == 5


def test_a_date_question_is_right_with_the_plain_date_and_a_status_question_needs_the_wording(
    smoke_docs,
):
    doc = next(d for d in smoke_docs if d.doc_id == "health_policy-1-photo")
    end = doc.fields["end_date"]
    base = lookup_question(doc, "end_date")
    box = base.box or (0.0, 0.0, 1.0, 1.0)
    truth, back = {doc.doc_id: doc}, {"db-1": doc.doc_id}

    def right(prompt: str, text: str) -> bool:
        q = base.model_copy(update={"prompt": prompt, "status": {"valid": True}})
        answer = an_answer("db-1", "end_date", end, text, [LineRef(base.page or 0, 0, box)])
        res = Result(Query(intent="lookup", field="end_date"), [], answer, [])
        return bool(judge(q, res, truth, back).answer_correct)

    assert right("When does the policy expire?", "31 Mar 2027")
    assert right("When does the policy expire?", "Yes, until 31 Mar 2027.")
    assert right("Is the policy still valid?", "Yes, until 31 Mar 2027.")
    assert not right("Is the policy still valid?", "31 Mar 2027")


# -- the eval decides which questions ask for a status on its own ---------------------------------


@pytest.mark.parametrize(
    "prompt",
    [
        "When does the PAN card expire?",
        "Kavita's car insurance expiry date",
        "When does the cover on the health policy end?",
        "Which insurer issued the AC warranty card?",
    ],
)
def test_a_date_question_needs_only_the_date(prompt):
    assert wants_status(prompt) is False


@pytest.mark.parametrize(
    "prompt",
    [
        "Is Kavita's car insurance still valid?",
        "Is the AC still under warranty?",
        "the passport still valid",
        "the AC under warranty",
        "Is it still valid?",
        "Is the passport still valod?",
    ],
)
def test_a_status_question_needs_the_status_wording(prompt):
    assert wants_status(prompt) is True


def test_the_eval_decides_on_its_own_without_the_app_classifier():
    import ast
    import inspect

    import evals.search_eval as search_eval
    import evals.search_set as search_set

    assert not hasattr(search_eval, "asks_status")
    names = {
        n.id
        for n in ast.walk(ast.parse(inspect.getsource(search_set.wants_status)))
        if isinstance(n, ast.Name)
    }
    assert "household_vault" not in names and "asks_status" not in names
    tree = ast.parse(Path(search_eval.__file__).read_text())
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    assert "asks_status" not in imported
