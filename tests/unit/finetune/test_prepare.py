import json
from pathlib import Path

import pytest

from finetune.prepare import prepare, to_example
from household_vault.safety import UnsafePathError
from household_vault.schemas import SCHEMAS
from spikes.extraction.prompt import SYSTEM, schema_json, user_prompt

SPIKE_SET = Path(__file__).resolve().parents[3] / "evals" / "datasets" / "spike-v0"
SPLIT = {"train": 0.7, "val": 0.15, "test": 0.15}


def _rows(out: Path, name: str) -> list[dict]:
    return [json.loads(ln) for ln in (out / f"{name}.jsonl").read_text().splitlines()]


def no_base_id_in_two_splits(out: Path) -> bool:
    seen: dict[str, str] = {}
    for name in SPLIT:
        for row in _rows(out, name):
            if seen.setdefault(row["base_id"], name) != name:
                return False
    return True


def test_example_answer_is_the_truth_json(spike_docs_all):
    ex = to_example(spike_docs_all[0], SCHEMAS[spike_docs_all[0].doc_type], None)
    assert json.loads(ex["messages"][-1]["content"]) == spike_docs_all[0].fields


def test_example_prompt_is_the_inference_prompt(spike_docs_all):
    doc = spike_docs_all[0]
    schema = SCHEMAS[doc.doc_type]
    ex = to_example(doc, schema, "line one\nline two")
    assert [m["role"] for m in ex["messages"]] == ["system", "user", "assistant"]
    assert ex["messages"][0]["content"] == SYSTEM
    assert ex["messages"][1]["content"] == user_prompt(
        doc.doc_type.value, schema_json(schema), "line one\nline two"
    )


def test_image_example_points_at_the_page_file(spike_docs_all):
    doc = spike_docs_all[0]
    ex = to_example(doc, SCHEMAS[doc.doc_type], None)
    assert ex["images"] == doc.files
    assert "attached image" in ex["messages"][1]["content"]
    assert to_example(doc, SCHEMAS[doc.doc_type], "text")["images"] == []


def test_variants_never_split_across_sets(tmp_path):
    counts = prepare(SPIKE_SET, tmp_path, SPLIT, seed=7)
    assert sum(counts.values()) == 36
    assert no_base_id_in_two_splits(tmp_path)


def test_every_split_gets_documents_and_counts_match_files(tmp_path):
    counts = prepare(SPIKE_SET, tmp_path, SPLIT, seed=7)
    assert all(n > 0 for n in counts.values())
    for name, n in counts.items():
        assert len(_rows(tmp_path, name)) == n


def test_same_seed_same_split_other_seed_differs(tmp_path):
    a, b, c = tmp_path / "a", tmp_path / "b", tmp_path / "c"
    prepare(SPIKE_SET, a, SPLIT, seed=7)
    prepare(SPIKE_SET, b, SPLIT, seed=7)
    prepare(SPIKE_SET, c, SPLIT, seed=8)
    assert (a / "test.jsonl").read_text() == (b / "test.jsonl").read_text()
    assert (a / "test.jsonl").read_text() != (c / "test.jsonl").read_text()


def test_fractions_must_sum_to_one(tmp_path):
    with pytest.raises(ValueError, match="sum to 1"):
        prepare(SPIKE_SET, tmp_path, {"train": 0.5, "val": 0.1}, seed=7)


def test_prepare_refuses_cloud_storage_output(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    with pytest.raises(UnsafePathError):
        prepare(SPIKE_SET, tmp_path / "Library" / "CloudStorage" / "x", SPLIT, seed=7)
