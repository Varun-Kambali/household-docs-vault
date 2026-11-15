"""Drift: the frozen spike-v0 set still parses, and the committed eval-v1 truth is what the
generator makes now. Locked PDFs carry a random encryption salt, so files are never compared,
only truth."""

import json
from pathlib import Path

import pytest
from vault_synth.cli import generate
from vault_synth.model import SynthDoc
from vault_synth.sets import LOCKABLE, load_set, locked_password

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
    fresh_docs = generate("eval-v1", tmp_path, splits=("val", "test"))
    committed_ids = [
        r["doc_id"] for r in json.loads((EVAL_V1 / "manifest.json").read_text())["documents"]
    ]
    fresh_ids = [d.doc_id for d in fresh_docs]
    assert set(fresh_ids) - set(committed_ids) == set(), "generated but not committed"
    assert set(committed_ids) - set(fresh_ids) == set(), "committed but not generated"
    assert len(fresh_ids) == len(set(fresh_ids))
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


def test_locked_pdfs_open_with_the_derived_password_and_truth_stores_none() -> None:
    from household_vault.reading.render import LockedPdfError, page_count

    locked = [d for d in load_set(EVAL_V1) if d.variant == "locked"]
    assert locked
    for d in locked:
        data = (EVAL_V1 / d.files[0]).read_bytes()
        with pytest.raises(LockedPdfError):
            page_count(data)
        assert page_count(data, password=locked_password(d.base_id)) == 1, d.doc_id
    for f in EVAL_V1.glob("*.json"):
        assert '"password"' not in f.read_text(), f.name


TODAY = "2026-11-12"
# (earlier, later, strict): the order every pair of dates on a page must keep
DATE_ORDER = (
    ("start_date", "premium_due_date", True),
    ("premium_due_date", "end_date", False),
    ("start_date", "end_date", True),
    ("purchase_date", "period_start", False),
    ("period_start", "period_end", True),
    ("date_of_birth", "issue_date", True),
    ("issue_date", "expiry_date", True),
    ("statement_date", "payment_due_date", True),
    ("date", "next_visit", False),
    ("document_date", "expiry_date", True),
)
NOT_AFTER_TODAY = (
    "purchase_date",
    "issue_date",
    "document_date",
    "date",
    "statement_date",
    "date_of_birth",
    "invoice_date",
    "start_date",
)


def test_dates_on_every_committed_document_keep_their_order() -> None:
    checked = 0
    for d in load_set(EVAL_V1):
        f = d.fields
        for a, b, strict in DATE_ORDER:
            if f.get(a) is not None and f.get(b) is not None:
                checked += 1
                x, y = str(f[a]), str(f[b])
                assert x < y or (x == y and not strict), (d.doc_id, a, b, x, y)
        for name in NOT_AFTER_TODAY:
            if f.get(name) is not None:
                assert str(f[name]) <= TODAY, (d.doc_id, name)
    assert checked > 100
