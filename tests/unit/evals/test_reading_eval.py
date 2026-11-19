from evals.reading_eval import (
    field_f1,
    person_ok,
    run_reading,
    silent_misfile,
    summarise_reading,
    write_results,
)
from household_vault.leakscan import scan_text
from household_vault.reading.engines import Engines
from household_vault.reading.recorded import recorded_engines
from household_vault.reasons import Reason
from tests.conftest import asked, doc_result, filed_to, truth_doc
from tests.fakes import EVAL_V1, TruthModels, TruthPages


def test_oracle_readings_score_perfectly(eval_slice, oracle_dir):
    s = summarise_reading(
        run_reading(
            EVAL_V1,
            "val",
            recorded_engines(oracle_dir),
            record_to=None,
            resume=False,
            limit=None,
            only=eval_slice,
        )
    )
    assert (s["type_accuracy"], s["field_exact"]["photo"], s["silent_misfiles_per_100"]) == (
        1.0,
        1.0,
        0,
    )


def test_person_and_misfile_rules():
    outsider = truth_doc(owner=None, folder=None, expected_ask=["person_unknown"])
    assert person_ok(outsider, asked(Reason.person_unknown)) is True
    assert person_ok(outsider, filed_to("p1", "Ravi Kumar Rao/Insurance")) is False
    kavita = truth_doc(owner="p2", folder="Kavita Rao/Insurance")
    assert silent_misfile(kavita, filed_to("p1", "Ravi Kumar Rao/Insurance"))
    assert not silent_misfile(kavita, asked(Reason.person_unsure))


def test_a_filled_unprinted_field_lowers_f1():
    r = doc_result(
        truth={"nominee": None, "policy_number": "P1"},
        got={"nominee": "X", "policy_number": "P1"},
    )
    assert r.fp == 1 and field_f1([r]) < 1.0


def test_results_hold_no_raw_output_or_card_number(tmp_path, oracle_dir, eval_slice):
    rows = run_reading(
        EVAL_V1,
        "val",
        recorded_engines(oracle_dir),
        record_to=None,
        resume=False,
        limit=None,
        only=eval_slice,
    )
    path = write_results(
        tmp_path, "reading", "val", summarise_reading(rows), [r.model_dump() for r in rows]
    )
    assert scan_text(path.read_text(), allow_test_cards=False) == []


def test_a_run_records_each_document_and_resume_replays_them(tmp_path, eval_slice):
    first = run_reading(
        EVAL_V1,
        "val",
        Engines(TruthPages(), TruthModels()),
        record_to=tmp_path,
        resume=False,
        limit=None,
        only=eval_slice,
    )
    assert len(list(tmp_path.glob("*.json"))) == len(eval_slice)
    # the models are down now: only a replay from the recordings can finish
    down = Engines(TruthPages(), TruthModels(down_first=10**6))
    again = run_reading(
        EVAL_V1, "val", down, record_to=tmp_path, resume=True, limit=None, only=eval_slice
    )
    assert [r.model_dump() for r in again] == [r.model_dump() for r in first]
    card = next(p for p in tmp_path.glob("*.json") if '"card_front-6-photo"' in p.read_text())
    assert "5105105105105100" in card.read_text()  # a published test number stays


def test_limit_and_only_pick_documents():
    rows = run_reading(
        EVAL_V1,
        "val",
        Engines(TruthPages(), TruthModels()),
        record_to=None,
        resume=False,
        limit=3,
        only=None,
    )
    assert len(rows) == 3
