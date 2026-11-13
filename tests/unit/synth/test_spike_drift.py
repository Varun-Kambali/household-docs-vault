"""The committed spike-v0 truth files must be what the generator makes today (seed 7).

PDFs and JPEGs are not compared byte for byte (library versions move them); the truth is.
"""

import json
from pathlib import Path

from vault_synth.model import SynthDoc

COMMITTED = Path(__file__).resolve().parents[3] / "evals" / "datasets" / "spike-v0"


def test_generator_matches_committed_truth(spike_docs_all: list[SynthDoc]) -> None:
    assert spike_docs_all
    for d in spike_docs_all:
        committed = json.loads((COMMITTED / f"{d.doc_id}.json").read_text())
        fresh = json.loads(d.model_dump_json())
        assert fresh["fields"] == committed["fields"], d.doc_id
        assert fresh["printed"] == committed["printed"], d.doc_id
        assert [ln["text"] for ln in fresh["lines"]] == [ln["text"] for ln in committed["lines"]], (
            d.doc_id
        )


def test_every_committed_truth_file_is_regenerated(spike_docs_all: list[SynthDoc]) -> None:
    made = {d.doc_id for d in spike_docs_all}
    on_disk = {p.stem for p in COMMITTED.glob("*-clean.json")} | {
        p.stem for p in COMMITTED.glob("*-photo.json")
    }
    assert made == on_disk


def test_manifest_records_generator_library_versions() -> None:
    libs = json.loads((COMMITTED / "manifest.json").read_text())["libraries"]
    assert set(libs) == {"faker", "reportlab", "pillow", "pypdfium2"}


def test_generate_writes_library_versions_into_its_manifest(
    spike_docs_all: list[SynthDoc], tmp_path_factory
) -> None:  # type: ignore[no-untyped-def]
    from vault_synth.cli import generate

    out = tmp_path_factory.mktemp("manifest-check")
    generate("spike-v0", per_type=1, seed=7, out=out)
    libs = json.loads((out / "manifest.json").read_text())["libraries"]
    assert set(libs) == {"faker", "reportlab", "pillow", "pypdfium2"}
    assert all(libs.values())
