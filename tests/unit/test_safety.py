import os
import pwd
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


needs_firmlink = pytest.mark.skipif(
    not Path("/System/Volumes/Data").is_dir(), reason="APFS firmlinks exist on macOS only"
)


@needs_firmlink
def test_firmlink_spelling_of_real_root_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = tmp_path / "real-vault"
    real.mkdir()
    monkeypatch.setenv("VAULT_REAL_ROOT", str(real))
    firm = Path("/System/Volumes/Data" + str(real.resolve()))
    assert firm.exists()
    with pytest.raises(UnsafePathError):
        assert_safe_path(firm / "Insurance" / "policy.pdf")
    with pytest.raises(UnsafePathError):
        assert_safe_path(firm)


def test_symlink_into_blocked_root_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = tmp_path / "real-vault"
    real.mkdir()
    monkeypatch.setenv("VAULT_REAL_ROOT", str(real))
    link = tmp_path / "innocent"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(UnsafePathError):
        assert_safe_path(link / "x.pdf")
    with pytest.raises(UnsafePathError):
        assert_safe_path(link)


def test_blocked_roots_follow_a_different_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_home = tmp_path / "fakehome"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    for rel in (
        "Library/CloudStorage/GoogleDrive-x",
        "Library/Application Support/household-vault/db",
        "Library/Application Support/Google/DriveFS/cache",
    ):
        with pytest.raises(UnsafePathError):
            assert_safe_path(fake_home / rel)
    # the account's own home (from the password database) stays blocked too
    real_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    with pytest.raises(UnsafePathError):
        assert_safe_path(real_home / "Library/CloudStorage/x")


def test_new_application_support_roots_are_refused() -> None:
    home = Path.home()
    for rel in (
        "Library/Application Support/household-vault/x.db",
        "Library/Application Support/Google/DriveFS/y",
    ):
        with pytest.raises(UnsafePathError):
            assert_safe_path(home / rel)
