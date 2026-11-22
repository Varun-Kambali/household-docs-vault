"""The search eval set: every question's truth is recomputed from the documents, and the files
are what the generator makes now."""

import json
from datetime import date
from pathlib import Path

import pytest
from vault_synth.cli import generate
from vault_synth.model import SynthDoc

from evals.search_set import (
    EVAL_TODAY,
    EVAL_V1,
    SEARCH_DIR,
    SET_SEED,
    Question,
    apply_query,
    build_questions,
    fits_something,
    load_questions,
    search_vault_docs,
    status_source,
    truth_value,
    write_set,
)
from household_vault.leakscan import scan_text
from household_vault.people import load_household

SPLITS = ("val", "test")


@pytest.fixture(scope="module", params=SPLITS)
def split(request: pytest.FixtureRequest) -> str:
    return str(request.param)


@pytest.fixture(scope="module")
def vault_docs(split: str) -> dict[str, SynthDoc]:
    return {d.doc_id: d for d in search_vault_docs(split)}  # type: ignore[arg-type]


@pytest.fixture(scope="module")
def search_set(split: str) -> list[Question]:
    return load_questions(split)  # type: ignore[arg-type]


def of_kind(qs: list[Question], kind: str) -> list[Question]:
    return [q for q in qs if q.kind == kind]


def test_every_lookup_target_holds_the_same_answer(
    search_set: list[Question], vault_docs: dict[str, SynthDoc]
) -> None:
    lookups = of_kind(search_set, "lookup")
    assert len(lookups) >= 90
    for q in lookups:
        assert {json.dumps(truth_value(vault_docs[t], q.field)) for t in q.targets} == {
            json.dumps(q.value)
        }, q.id


def test_only_filed_documents_are_targets(
    search_set: list[Question], vault_docs: dict[str, SynthDoc]
) -> None:
    for q in search_set:
        assert all(not vault_docs[t].expected_ask for t in q.targets), q.id
        assert all(not vault_docs[t].expected_ask for t in q.expected or []), q.id


def test_list_truth_is_recomputed_from_the_documents(
    search_set: list[Question], vault_docs: dict[str, SynthDoc]
) -> None:
    lists = of_kind(search_set, "list")
    assert len(lists) >= 35
    for q in lists:
        assert q.query is not None and q.expected
        assert sorted(q.expected) == sorted(apply_query(q.query, vault_docs.values())), q.id


def test_list_queries_come_from_resolve_and_leave_nothing_unread(
    search_set: list[Question],
) -> None:
    for q in of_kind(search_set, "list"):
        assert q.query is not None and q.query.intent == "list"
        assert q.query.unread == [] and q.query.words == ""
        assert (q.query.range is None) == (q.query.role is None), q.id
        span = q.query.range
        if span and span.start and span.end:
            assert span.start <= span.end


def test_none_prompts_fit_no_document(
    search_set: list[Question], vault_docs: dict[str, SynthDoc]
) -> None:
    nones = of_kind(search_set, "none")
    assert len(nones) >= 18
    for q in nones:
        assert q.query is not None and q.targets == [] and q.expected == []
        assert not fits_something(q.query, list(vault_docs.values())), q.id


def test_every_truth_box_holds_the_printed_value(
    search_set: list[Question], vault_docs: dict[str, SynthDoc]
) -> None:
    checked = 0
    for q in search_set:
        if q.kind != "lookup":
            assert q.page is None and q.box is None
            continue
        doc = vault_docs[q.targets[0]]
        assert q.page is not None and q.box is not None, q.id
        name = status_source(doc.doc_type, q.field or "") or q.field
        assert name is not None
        idx = doc.field_lines[name]
        line = doc.lines[idx[0]]
        assert (line.page, line.bbox) == (q.page, q.box), q.id
        assert doc.printed[name] in line.text, q.id
        checked += 1
    assert checked > 80


def test_a_filed_document_is_never_both_unfiled_and_asked_about(
    search_set: list[Question], vault_docs: dict[str, SynthDoc]
) -> None:
    left_out = {i for i, d in vault_docs.items() if d.expected_ask}
    assert left_out
    assert not left_out & {t for q in search_set for t in q.targets}


def test_every_kind_and_style_is_present(search_set: list[Question]) -> None:
    assert {q.kind for q in search_set} == {"lookup", "find", "list", "none"}
    assert {q.style for q in search_set} == {"question", "terse", "typo", "synonym"}
    assert {q.origin for q in search_set} == {"eval-v1", "extra"}
    assert len({q.id for q in search_set}) == len(search_set)
    assert len({q.prompt for q in search_set}) == len(search_set)


def test_the_vault_is_about_three_times_the_eval_documents(
    vault_docs: dict[str, SynthDoc],
) -> None:
    origins = [d.set_name for d in vault_docs.values()]
    assert origins.count("eval-v1") == 59 and len(origins) == 59 * 3
    assert {d.variant for d in vault_docs.values() if d.set_name == "eval-v1"} == {"photo"}


def test_the_committed_questions_are_what_the_builder_makes(
    split: str, vault_docs: dict[str, SynthDoc]
) -> None:
    household = load_household(EVAL_V1 / "household.json")
    fresh = build_questions(list(vault_docs.values()), household, split, EVAL_TODAY, SET_SEED)  # type: ignore[arg-type]
    text = (SEARCH_DIR / f"{split}.jsonl").read_text()
    assert text == "".join(q.model_dump_json() + "\n" for q in fresh)


def test_the_extra_sets_build_byte_for_byte_the_same(tmp_path: Path) -> None:
    for name in ("search-x1", "search-x2"):
        generate(name, tmp_path / name, splits=("val", "test"), variants=("clean",))
        committed = SEARCH_DIR / "extra" / name
        made = sorted(p.name for p in (tmp_path / name).iterdir())
        assert made == sorted(p.name for p in committed.iterdir())
        for fname in made:
            assert (tmp_path / name / fname).read_bytes() == (committed / fname).read_bytes(), (
                name,
                fname,
            )


def test_the_set_holds_no_real_shaped_number() -> None:
    text = "".join(
        p.read_text()
        for p in SEARCH_DIR.rglob("*")
        if p.is_file() and p.suffix in {".json", ".jsonl", ".md"}
    )
    assert scan_text(text, allow_test_cards=True) == []


def test_extra_pages_of_ids_carry_specimen() -> None:
    from vault_synth.sets import load_set

    for name in ("search-x1", "search-x2"):
        for d in load_set(SEARCH_DIR / "extra" / name):
            if d.doc_type.value in {"aadhaar", "pan", "passport", "voter_id", "driving_licence"}:
                assert any("SPECIMEN" in ln.text for ln in d.lines), d.doc_id


def test_the_summary_counts_the_documents_left_out(tmp_path: Path) -> None:
    sums = write_set(tmp_path)
    for s in SPLITS:
        assert (
            sums[s]["documents_left_out"]
            == json.loads((SEARCH_DIR / "summary.json").read_text())[s]["documents_left_out"]
        )
        assert sums[s]["by_kind"]
    assert date(2026, 11, 20) == EVAL_TODAY
