"""Shared fixtures. The spike set is generated once per session (seed 7, two per type)."""

from collections.abc import Callable
from pathlib import Path

import pytest
from vault_synth.cli import generate
from vault_synth.model import SynthDoc

from household_vault.doctypes import DocType


@pytest.fixture(scope="session")
def spike_docs_all(tmp_path_factory: pytest.TempPathFactory) -> list[SynthDoc]:
    out: Path = tmp_path_factory.mktemp("spike-v0")
    return generate("spike-v0", per_type=2, seed=7, out=out)


@pytest.fixture(scope="session")
def spike_docs(spike_docs_all: list[SynthDoc]) -> Callable[[DocType], list[SynthDoc]]:
    def of_type(doc_type: DocType) -> list[SynthDoc]:
        return [d for d in spike_docs_all if d.doc_type == doc_type]

    return of_type
