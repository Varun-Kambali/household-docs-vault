"""Shared fixtures. The spike set is generated once per session (seed 7, two per type)."""

from collections.abc import Callable
from pathlib import Path

import pytest
from vault_synth.cli import generate
from vault_synth.model import SynthDoc

from household_vault import safety
from household_vault.doctypes import DocType


@pytest.fixture(autouse=True)
def fake_homes(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point $HOME and the password-database home at temp folders for every test.

    The path guard stats folders under the home's Library; no test may look at the real one.
    Returns the $HOME folder; the password-database home is a sibling called "pwd-home".
    """
    base = tmp_path_factory.mktemp("homes")
    home, pwd_home = base / "home", base / "pwd-home"
    home.mkdir()
    pwd_home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("VAULT_REAL_ROOT", raising=False)
    monkeypatch.setattr(safety, "_pwd_home", lambda: pwd_home)
    return home


@pytest.fixture(scope="session")
def spike_docs_all(tmp_path_factory: pytest.TempPathFactory) -> list[SynthDoc]:
    out: Path = tmp_path_factory.mktemp("spike-v0")
    return generate("spike-v0", per_type=2, seed=7, out=out)


@pytest.fixture(scope="session")
def spike_docs(spike_docs_all: list[SynthDoc]) -> Callable[[DocType], list[SynthDoc]]:
    def of_type(doc_type: DocType) -> list[SynthDoc]:
        return [d for d in spike_docs_all if d.doc_type == doc_type]

    return of_type
