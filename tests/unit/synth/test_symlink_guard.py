from pathlib import Path

import pytest
from vault_synth import visits
from vault_synth.cli import generate

from household_vault.safety import UnsafePathError


def _planted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str) -> tuple[Path, Path, Path]:
    real = tmp_path / "real-vault"
    real.mkdir()
    monkeypatch.setenv("VAULT_REAL_ROOT", str(real))
    out = tmp_path / "out"
    out.mkdir()
    target = real / "victim.txt"
    target.write_text("original")
    (out / name).symlink_to(target)
    return real, out, target


def test_generate_refuses_a_planted_manifest_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, out, target = _planted(tmp_path, monkeypatch, "manifest.json")
    with pytest.raises(UnsafePathError):
        generate("spike-v0", 1, 7, out)
    assert target.read_text() == "original"


def test_generate_refuses_a_planted_truth_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, out, target = _planted(tmp_path, monkeypatch, "health_policy-1-clean.json")
    with pytest.raises(UnsafePathError):
        generate("spike-v0", 1, 7, out)
    assert target.read_text() == "original"


def test_visit_build_refuses_a_planted_truth_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, out, target = _planted(tmp_path, monkeypatch, "visit_1.json")
    stats = {"duration_seconds": 0.0, "measured_snr_db": 0.0}
    monkeypatch.setattr(visits, "render", lambda *a, **k: stats)  # no audio needed here
    with pytest.raises(UnsafePathError):
        visits.build(out)
    assert target.read_text() == "original"
