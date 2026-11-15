"""Drift: the frozen spike-v0 set still parses, and the committed eval-v1 truth is what the
generator makes now. Locked PDFs carry a random encryption salt, so files are never compared,
only truth."""

import json
from pathlib import Path

from vault_synth.cli import generate
from vault_synth.model import SynthDoc
from vault_synth.sets import LOCKABLE, load_set

from household_vault.doctypes import DocType
from tests.conftest import EVAL_V1, group_by_base

COMMITTED = Path(__file__).resolve().parents[3] / "evals" / "datasets" / "spike-v0"
LIBRARIES = {"faker", "reportlab", "pillow", "pypdfium2"}


def test_manifest_records_generator_library_versions() -> None:
    libs = json.loads((COMMITTED / "manifest.json").read_text())["libraries"]
    assert set(libs) == LIBRARIES


def test_the_frozen_set_still_parses_as_version_two(spike_docs_all: list[SynthDoc]) -> None:
    assert len(spike_docs_all) == 36
    assert all(d.set_name == "spike-v0" and d.split is None for d in spike_docs_all)


def test_generate_writes_library_versions_into_its_manifest(tmp_path: Path) -> None:
    generate("eval-v1", tmp_path, splits=("test",), types=[DocType.pan])
    libs = json.loads((tmp_path / "manifest.json").read_text())["libraries"]
    assert set(libs) == LIBRARIES
    assert all(libs.values())


def test_committed_eval_set_shape() -> None:
    docs = load_set(EVAL_V1)
    assert {d.split for d in docs} == {"val", "test"}
    for split in ("val", "test"):
        bases = group_by_base([d for d in docs if d.split == split])
        assert len(bases) == 9 * 2 + 41
        for base in bases.values():
            assert {"clean", "photo", "scan"} <= {d.variant for d in base}
            assert ("locked" in {d.variant for d in base}) == (base[0].doc_type in LOCKABLE)


def test_committed_truth_matches_the_generator(tmp_path: Path) -> None:
    types = [DocType.health_policy, DocType.aadhaar, DocType.utility_bill, DocType.passport]
    fresh_docs = generate("eval-v1", tmp_path, splits=("test",), types=types)
    assert fresh_docs
    for d in fresh_docs:
        committed = json.loads((EVAL_V1 / f"{d.doc_id}.json").read_text())
        fresh = json.loads(d.model_dump_json())
        for key in ("fields", "printed", "owner", "folder", "expected_ask", "field_lines"):
            assert fresh[key] == committed[key], (d.doc_id, key)
        assert [ln["text"] for ln in fresh["lines"]] == [ln["text"] for ln in committed["lines"]]


def test_the_split_guarantees_hold_in_the_committed_set() -> None:
    docs = load_set(EVAL_V1)
    clean = [d for d in docs if d.variant == "clean"]
    for split, base in (("val", 1), ("test", 5)):
        rx = next(d for d in clean if d.doc_id == f"prescription-{base}-clean")
        assert rx.split == split and rx.owner is None and "person_unknown" in rx.expected_ask
        pan = next(d for d in clean if d.doc_id == f"pan-{base}-clean")
        assert pan.split == split and pan.fields["number"] is None
        assert "missing_required" in pan.expected_ask
