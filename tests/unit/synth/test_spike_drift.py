"""The frozen spike-v0 set: its manifest still records its libraries, and the generator that
now builds eval-v1 records the same ones. (Task 13 adds the eval-v1 drift test.)"""

import json
from pathlib import Path

from vault_synth.cli import generate
from vault_synth.model import SynthDoc

from household_vault.doctypes import DocType

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
