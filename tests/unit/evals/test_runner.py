import json
from pathlib import Path

from vault_synth.sets import load_set

from evals.recordings import smoke_selection
from evals.runner import (
    SMOKE_RECORDINGS,
    check_smoke,
    load_thresholds,
    main,
    smoke_metrics,
    write_summary,
)
from household_vault.leakscan import scan_text
from tests.fakes import EVAL_V1


def break_one_recording(folder: Path) -> None:
    """Turn the recorded fill of one document into broken JSON."""
    for path in folder.glob("*.json"):
        rec = json.loads(path.read_text())
        if rec["doc_id"] == "health_policy-1-photo":
            rec["fill_raw"] = "{not json"
            path.write_text(json.dumps(rec))
            return
    raise AssertionError("the recording to break is missing")


def test_smoke_fails_below_its_threshold(oracle_dir, capsys):
    break_one_recording(oracle_dir)  # turns one recorded fill into broken JSON
    assert main(["smoke", "--recordings", str(oracle_dir)]) == 1
    out = capsys.readouterr().out
    assert "field_exact_photo" in out and "below the minimum" in out


def test_smoke_passes_on_the_committed_recordings(capsys):
    assert main(["smoke"]) == 0
    assert "smoke run passed on 22 documents" in capsys.readouterr().out


def test_smoke_fails_when_a_recording_is_missing(oracle_dir, capsys):
    next(oracle_dir.glob("*.json")).unlink()
    assert main(["smoke", "--recordings", str(oracle_dir)]) == 1
    assert "no recording" in capsys.readouterr().out


def test_the_committed_smoke_list_follows_its_written_rule():
    committed = json.loads((EVAL_V1 / "smoke.json").read_text())["documents"]
    assert committed == smoke_selection(load_set(EVAL_V1))
    assert len(committed) == len(set(committed)) and 20 <= len(committed) <= 26


def test_the_committed_smoke_recordings_hold_no_secret_or_password():
    from vault_synth.sets import locked_password

    passwords = {locked_password(d.base_id) for d in load_set(EVAL_V1) if d.variant == "locked"}
    for path in SMOKE_RECORDINGS.glob("*.json"):
        text = path.read_text()
        assert scan_text(text, allow_test_cards=True) == [], path.name
        assert not any(p in text for p in passwords), path.name


def test_thresholds_name_only_known_metrics():
    thresholds = load_thresholds()["smoke"]
    metrics = smoke_metrics(
        {
            "type_accuracy": 1.0,
            "person_accuracy": 1.0,
            "linked_accuracy": 1.0,
            "field_exact": {"photo": 1.0, "all": 1.0},
            "line_recall_photo": 1.0,
            "silent_misfiles_per_100": 0.0,
            "needs_a_look_share": {"expected_clean": 0.0},
        },
        {
            "placement_matches_decision": 1.0,
            "documents_placed": 12,
            "exact_copies": 4,
            "undo_tried": 1,
            "exact_copies_caught": 1.0,
            "undo_same_path": 1.0,
            "wrong_merges": 0,
            "secrets_found": 0,
            "cvv_stored": 0,
            "inbox_left": 0,
            "needs_a_look_share": {"expected_clean": 0.0},
        },
    )
    assert set(thresholds["min"]) | set(thresholds["max"]) <= set(metrics)
    assert check_smoke(metrics, load_thresholds()) == []
    assert check_smoke({**metrics, "wrong_merges": 1}, load_thresholds()) == [
        "wrong_merges: 1 is above the maximum 0"
    ]


def test_a_reading_run_writes_results_and_the_test_summary(
    oracle_dir, eval_slice, tmp_path, monkeypatch
):
    import evals.runner as runner

    run = runner.run_reading
    monkeypatch.setattr(runner, "run_reading", lambda *a, **k: run(*a, **{**k, "only": eval_slice}))
    results = tmp_path / "results"
    argv = ["--engines", "recorded", "--record", str(oracle_dir), "--results", str(results)]
    assert main(["reading", "--split", "val", *argv]) == 0
    (path,) = results.glob("*_reading_val_*.json")
    body = json.loads(path.read_text())
    assert body["dataset"]["name"] == "eval-v1" and len(body["dataset"]["manifest_sha256"]) == 64
    assert body["prompt_version"] == "v4" and body["run"]["commit"]
    assert body["models"] == {"recorded_engines": ["oracle"]}
    assert not (results / "summary.md").exists()  # only the test split writes it


def test_summary_md_leads_with_the_headline_and_copies_the_newest_test_results(tmp_path):
    reading = {
        "run": {"date": "2026-12-01", "machine": "Mac", "commit": "abc1234"},
        "models": {"tags": {"qwen3-vl:4b": "sha256:x"}},
        "summary": {
            "documents": 10,
            "type_accuracy": 0.9,
            "person_accuracy": 0.8,
            "field_exact": {"all": 0.7, "photo": 0.6, "clean": 0.8, "scan": 0.5, "locked": 0.9},
            "line_recall_photo": 0.95,
            "silent_misfiles_per_100": 1.5,
            "needs_a_look_share": {"expected_clean": 0.1, "all": 0.2},
            "seconds_photo": {"median": 30.0, "max": 41.0},
        },
    }
    older = {**reading, "summary": {**reading["summary"], "type_accuracy": 0.1}}
    (tmp_path / "2026-11-01_reading_test_old1111.json").write_text(json.dumps(older))
    (tmp_path / "2026-12-01_reading_test_abc1234.json").write_text(json.dumps(reading))
    text = write_summary(tmp_path).read_text()
    assert text.splitlines()[2].startswith("**Fields exactly right on photos: 60.0%**")
    assert "| Type accuracy | 90.0% |" in text


def test_summary_md_is_not_written_without_test_results(tmp_path):
    assert write_summary(tmp_path) is None
    assert not (tmp_path / "summary.md").exists()


def test_a_run_that_places_copies_or_undoes_nothing_fails_the_smoke_check():
    thresholds = load_thresholds()
    reading = {
        "type_accuracy": 1.0,
        "person_accuracy": 1.0,
        "linked_accuracy": 1.0,
        "field_exact": {"photo": 1.0, "all": 1.0},
        "line_recall_photo": 1.0,
        "silent_misfiles_per_100": 0.0,
        "needs_a_look_share": {"expected_clean": 0.0},
    }
    filing = {
        "placement_matches_decision": 1.0,
        "documents_placed": 12,
        "exact_copies": 4,
        "undo_tried": 1,
        "exact_copies_caught": 1.0,
        "undo_same_path": 1.0,
        "wrong_merges": 0,
        "secrets_found": 0,
        "cvv_stored": 0,
        "inbox_left": 0,
        "needs_a_look_share": {"expected_clean": 0.0},
    }
    assert check_smoke(smoke_metrics(reading, filing), thresholds) == []
    for name in ("documents_placed", "exact_copies", "undo_tried"):
        misses = check_smoke(smoke_metrics(reading, {**filing, name: 0}), thresholds)
        assert misses == [f"{name}: 0 is below the minimum 1"]
