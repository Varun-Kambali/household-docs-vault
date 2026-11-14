import subprocess
from types import SimpleNamespace

import pytest

from household_vault import results
from household_vault.results import machine_name, run_meta


def fake_git(monkeypatch: pytest.MonkeyPatch, status: str = "", commit: str = "abc1234"):
    """Replace subprocess.run in results; returns the list of argument lists it was called with."""
    calls: list[list[str]] = []

    def run(cmd, **kwargs):
        calls.append(list(cmd))
        out = commit if "rev-parse" in cmd else status
        return SimpleNamespace(stdout=out + "\n", returncode=0)

    monkeypatch.setattr(results.subprocess, "run", run)
    return calls


def fake_sysctl(monkeypatch: pytest.MonkeyPatch, brand: str, memsize: str):
    monkeypatch.setattr(results.platform, "system", lambda: "Darwin")

    def run(cmd, **kwargs):
        value = brand if "machdep.cpu.brand_string" in cmd else memsize
        return SimpleNamespace(stdout=value + "\n", returncode=0)

    monkeypatch.setattr(results.subprocess, "run", run)


def test_dirty_flag_ignores_results_and_recordings(monkeypatch):
    calls = fake_git(monkeypatch, status="")
    assert run_meta().code_dirty is False
    assert ":(exclude,glob)**/results/**" in calls[-1] and ":(exclude)evals/recordings" in calls[-1]


def test_dirty_flag_set_by_changes(monkeypatch):
    fake_git(monkeypatch, status=" M src/x.py")
    meta = run_meta()
    assert meta.code_dirty is True and meta.commit == "abc1234"


def test_machine_name_on_a_mac(monkeypatch):
    fake_sysctl(monkeypatch, brand="Apple M5", memsize=str(16 * 2**30))
    assert machine_name() == "Apple M5, 16 GB"


def test_machine_name_elsewhere(monkeypatch):
    monkeypatch.setattr(results.platform, "system", lambda: "Linux")
    monkeypatch.setattr(results.platform, "machine", lambda: "x86_64")
    assert machine_name() == "x86_64, Linux"


def test_machine_name_survives_a_failed_sysctl(monkeypatch):
    monkeypatch.setattr(results.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(results.platform, "machine", lambda: "arm64")

    def boom(*a, **k):
        raise subprocess.CalledProcessError(1, "sysctl")

    monkeypatch.setattr(results.subprocess, "run", boom)
    assert machine_name() == "arm64, Darwin"
