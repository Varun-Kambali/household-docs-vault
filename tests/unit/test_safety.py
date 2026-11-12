from pathlib import Path

import pytest

from household_vault.safety import UnsafePathError, assert_safe_path


def test_assert_safe_path_refuses_cloud_storage(tmp_path: Path) -> None:
    with pytest.raises(UnsafePathError):
        assert_safe_path(Path.home() / "Library/CloudStorage/GoogleDrive-x/My Drive/Family Vault")
    assert assert_safe_path(tmp_path) == tmp_path.resolve()


def test_assert_safe_path_refuses_real_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = tmp_path / "real-vault"
    monkeypatch.setenv("VAULT_REAL_ROOT", str(real))
    with pytest.raises(UnsafePathError):
        assert_safe_path(real / "Insurance" / "policy.pdf")
    assert assert_safe_path(tmp_path / "other") == (tmp_path / "other").resolve()


def test_assert_safe_path_refuses_dotdot_escape(tmp_path: Path) -> None:
    sneaky = Path.home() / "Library/CloudStorage/x/../GoogleDrive-y"
    with pytest.raises(UnsafePathError):
        assert_safe_path(sneaky)


def test_assert_safe_path_ignores_case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(UnsafePathError):
        assert_safe_path(Path.home() / "library/cloudstorage/GoogleDrive-x")
    monkeypatch.setenv("VAULT_REAL_ROOT", str(tmp_path / "Real-Vault"))
    with pytest.raises(UnsafePathError):
        assert_safe_path(tmp_path / "real-vault" / "a.pdf")
