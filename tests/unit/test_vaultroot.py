import errno
import os
from pathlib import Path

import pytest

from household_vault.safety import UnsafePathError
from household_vault.vaultroot import CopyMismatch, VaultGone, VaultPathError, VaultRoot
from tests.conftest import raise_


@pytest.mark.parametrize(
    "rel", ["/etc/passwd", "../x", "Inbox/../../x", "Inbox/a\x00b", "", "Inbox//a"]
)
def test_path_rejects_escapes(vault: VaultRoot, rel: str) -> None:
    with pytest.raises(VaultPathError):
        vault.path(rel)


def test_a_symlinked_folder_or_file_is_refused(vault: VaultRoot, tmp_path: Path) -> None:
    (tmp_path / "out").mkdir()
    (vault.root / "Linked").symlink_to(tmp_path / "out", target_is_directory=True)
    (tmp_path / "victim.txt").write_text("original")
    (vault.root / "Inbox" / "a.pdf").symlink_to(tmp_path / "victim.txt")
    for call in (
        lambda: vault.path("Linked/a.pdf"),
        lambda: vault.read_bytes("Inbox/a.pdf"),
        lambda: vault.write_atomic("Inbox/a.pdf", b"x"),
    ):
        with pytest.raises(VaultPathError):
            call()
    assert (tmp_path / "victim.txt").read_text() == "original"


def test_copy_verified_never_overwrites_and_leaves_no_partial(vault: VaultRoot) -> None:
    vault.write_atomic("Inbox/a.pdf", b"%PDF-1.4 a")
    vault.write_atomic("Home/b.pdf", b"other")
    with pytest.raises(FileExistsError):
        vault.copy_verified("Inbox/a.pdf", "Home/b.pdf", vault.sha256("Inbox/a.pdf"))
    with pytest.raises(CopyMismatch):
        vault.copy_verified("Inbox/a.pdf", "Home/c.pdf", "0" * 64)
    with pytest.raises(VaultGone):
        vault.read_bytes("Inbox/missing.pdf")
    assert vault.read_bytes("Home/b.pdf") == b"other"
    assert {e.name for e in vault.list_dir("Home")} == {"b.pdf"}
    assert vault.free_name("Home", "b.pdf") == "b (2).pdf"


def test_copy_and_move_work_where_hard_links_do_not(
    vault: VaultRoot, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(os, "link", raise_(OSError(errno.ENOTSUP, "no hard links")))
    vault.write_atomic("Inbox/a.pdf", b"%PDF-1.4 a")
    vault.copy_verified("Inbox/a.pdf", "Home/a.pdf", vault.sha256("Inbox/a.pdf"))
    vault.move("Inbox/a.pdf", "Needs a look/a.pdf")
    with pytest.raises(FileExistsError):
        vault.move("Needs a look/a.pdf", "Home/a.pdf")
    assert vault.read_bytes("Home/a.pdf") == vault.read_bytes("Needs a look/a.pdf")


def test_app_mode_allows_cloud_root_dev_mode_does_not(fake_homes: Path) -> None:
    cloud = fake_homes / "Library/CloudStorage/GoogleDrive-x/My Drive/Family Vault"
    with pytest.raises(UnsafePathError):
        VaultRoot(cloud, mode="dev")
    assert VaultRoot(cloud, mode="app").root == cloud.resolve()


def test_append_unlink_mkdirs_and_listing(vault: VaultRoot, tmp_path: Path) -> None:
    vault.mkdirs("_system/log")
    vault.append_text("_system/log/a.csv", "a\n")
    vault.append_text("_system/log/a.csv", "b\n")
    assert vault.read_bytes("_system/log/a.csv") == b"a\nb\n"
    (vault.root / "Home" / "ln").symlink_to(tmp_path)
    kinds = {e.name: e.kind for e in vault.list_dir("Home")}
    assert kinds == {"ln": "symlink"}
    assert {e.name: e.kind for e in vault.list_dir("_system")} == {"log": "dir"}
    vault.unlink("Home/ln")
    vault.unlink("_system/log/a.csv")
    with pytest.raises(VaultGone):
        vault.unlink("_system/log/a.csv")
    with pytest.raises(VaultGone):
        vault.list_dir("Nowhere")
    with pytest.raises(VaultGone):
        vault.write_atomic("Nowhere/x.pdf", b"x")


def test_move_of_a_missing_file_and_free_name_without_extension(vault: VaultRoot) -> None:
    with pytest.raises(VaultGone):
        vault.move("Inbox/none.pdf", "Home/none.pdf")
    vault.write_atomic("Home/notes", b"x")
    assert vault.free_name("Home", "notes") == "notes (2)"
    assert vault.free_name("Home", "new.pdf") == "new.pdf"
