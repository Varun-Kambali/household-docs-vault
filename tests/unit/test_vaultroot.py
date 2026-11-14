import errno
import os
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from household_vault import vaultroot as vr
from household_vault.vaultroot import (
    MAX_NAME_BYTES,
    CopyMismatch,
    VaultGone,
    VaultPathError,
    VaultRoot,
    check_component,
)
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


@pytest.fixture
def plant(vault: VaultRoot, monkeypatch: pytest.MonkeyPatch) -> Callable[[str, bytes], None]:
    """Make a file appear while a copy is between its fsync and its placement."""

    def arm(rel: str, data: bytes) -> None:
        real = vr._sync_file

        def planting(fd: int) -> None:
            real(fd)
            if not vault.exists(rel):
                (vault.root / rel).write_bytes(data)

        monkeypatch.setattr(vr, "_sync_file", planting)

    return arm


def test_unlink_through_a_swapped_root_stays_inside(vault: VaultRoot, tmp_path: Path) -> None:
    out = tmp_path / "out"
    (out / "Home").mkdir(parents=True)
    (out / "Home" / "keep.txt").write_text("outside")
    vault.root.rename(tmp_path / "vault.real")
    vault.root.symlink_to(out, target_is_directory=True)
    for call in (lambda: vault.unlink("Home/keep.txt"), lambda: vault.read_bytes("Home/keep.txt")):
        with pytest.raises(VaultPathError):
            call()
    assert (out / "Home" / "keep.txt").read_text() == "outside"


def test_names_are_limited_to_246_utf8_bytes() -> None:
    assert MAX_NAME_BYTES == 246
    assert check_component("a" * 246) == "a" * 246
    assert check_component("\u00e9" * 123) == "\u00e9" * 123
    for bad in ("a" * 247, "\u00e9" * 124, "\U0001f600" * 62):
        with pytest.raises(VaultPathError):
            check_component(bad)


@pytest.mark.parametrize(
    "name", ["a\x85b", "a\x9fb", "a\u202eb", "a\u2069b", "a\u200fb", "a\u200eb", "a\u061cb"]
)
def test_names_refuse_c1_and_bidi_controls(name: str) -> None:
    with pytest.raises(VaultPathError):
        check_component(name)


def test_a_destination_planted_mid_copy_is_not_replaced(
    vault: VaultRoot, plant: Callable[[str, bytes], None]
) -> None:
    vault.write_atomic("Inbox/a.pdf", b"new")
    plant("Home/a.pdf", b"user file")
    with pytest.raises(FileExistsError):
        vault.copy_verified("Inbox/a.pdf", "Home/a.pdf", vault.sha256("Inbox/a.pdf"))
    assert vault.read_bytes("Home/a.pdf") == b"user file"
    assert {e.name for e in vault.list_dir("Home")} == {"a.pdf"}


@pytest.mark.skipif(sys.platform != "darwin", reason="renamex_np is macOS only")
def test_a_destination_planted_before_the_rename_is_not_replaced(
    vault: VaultRoot, plant: Callable[[str, bytes], None], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(os, "link", raise_(OSError(errno.ENOTSUP, "no hard links")))
    vault.write_atomic("Inbox/a.pdf", b"new")
    plant("Home/a.pdf", b"user file")
    with pytest.raises(FileExistsError):
        vault.copy_verified("Inbox/a.pdf", "Home/a.pdf", vault.sha256("Inbox/a.pdf"))
    assert vault.read_bytes("Home/a.pdf") == b"user file"
    assert {e.name for e in vault.list_dir("Home")} == {"a.pdf"}


def test_move_onto_an_existing_name_with_real_hard_links(vault: VaultRoot) -> None:
    vault.write_atomic("Inbox/a.pdf", b"one")
    vault.write_atomic("Home/a.pdf", b"two")
    with pytest.raises(FileExistsError):
        vault.move("Inbox/a.pdf", "Home/a.pdf")
    assert vault.read_bytes("Inbox/a.pdf") == b"one"
    assert vault.read_bytes("Home/a.pdf") == b"two"
    vault.move("Inbox/a.pdf", "Home/b.pdf")
    assert not vault.exists("Inbox/a.pdf")
    assert vault.read_bytes("Home/b.pdf") == b"one"


def test_a_new_file_at_the_source_name_survives_a_rename_move(
    vault: VaultRoot, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(os, "link", raise_(OSError(errno.ENOTSUP, "no hard links")))
    real = vr._rename_noreplace

    def rename_then_arrive(src: Path, dst: Path) -> None:
        real(src, dst)
        src.write_bytes(b"arrived later")

    monkeypatch.setattr(vr, "_rename_noreplace", rename_then_arrive)
    vault.write_atomic("Inbox/a.pdf", b"first")
    vault.move("Inbox/a.pdf", "Home/a.pdf")
    assert vault.read_bytes("Home/a.pdf") == b"first"
    assert vault.read_bytes("Inbox/a.pdf") == b"arrived later"


def test_any_link_failure_falls_back_to_a_rename(
    vault: VaultRoot, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(os, "link", raise_(OSError(102, "operation not supported on socket")))
    vault.write_atomic("Inbox/a.pdf", b"x")
    vault.copy_verified("Inbox/a.pdf", "Home/a.pdf", vault.sha256("Inbox/a.pdf"))
    vault.move("Inbox/a.pdf", "Home/b.pdf")
    assert vault.read_bytes("Home/b.pdf") == b"x" == vault.read_bytes("Home/a.pdf")


def test_planted_links_at_the_temp_names_are_replaced_not_followed(
    vault: VaultRoot, tmp_path: Path
) -> None:
    victim = tmp_path / "victim.txt"
    victim.write_text("original")
    (vault.root / "Home" / ".x.pdf.tmp").symlink_to(victim)
    (vault.root / "Home" / ".y.pdf.partial").symlink_to(victim)
    vault.write_atomic("Home/x.pdf", b"data")
    vault.write_atomic("Inbox/y.pdf", b"data")
    vault.copy_verified("Inbox/y.pdf", "Home/y.pdf", vault.sha256("Inbox/y.pdf"))
    assert victim.read_text() == "original"
    assert vault.read_bytes("Home/x.pdf") == vault.read_bytes("Home/y.pdf") == b"data"


def _swap_for_link(
    monkeypatch: pytest.MonkeyPatch, vault: VaultRoot, rel: str, victim: Path
) -> None:
    real = VaultRoot.path

    def racy(self: VaultRoot, r: str) -> Path:
        p = real(self, r)
        if r == rel and p.exists() and not p.is_symlink():
            p.unlink()
            p.symlink_to(victim)
        return p

    monkeypatch.setattr(VaultRoot, "path", racy)


def test_a_link_swapped_in_after_the_check_is_refused(
    vault: VaultRoot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    victim = tmp_path / "victim.txt"
    victim.write_text("original")
    vault.write_atomic("Inbox/a.pdf", b"x")
    vault.append_text("Home/log.csv", "a\n")
    _swap_for_link(monkeypatch, vault, "Inbox/a.pdf", victim)
    _swap_for_link(monkeypatch, vault, "Home/log.csv", victim)
    with pytest.raises(VaultPathError):
        vault.read_bytes("Inbox/a.pdf")
    with pytest.raises(VaultPathError):
        vault.append_text("Home/log.csv", "b\n")
    assert victim.read_text() == "original"


def test_only_regular_files_can_be_read(vault: VaultRoot) -> None:
    os.mkfifo(vault.root / "Inbox" / "pipe")
    vault.write_atomic("Home/f", b"x")
    for call in (
        lambda: vault.read_bytes("Inbox/pipe"),
        lambda: vault.sha256("Home"),
        lambda: vault.copy_verified("Home", "Inbox/copy", "0" * 64),
    ):
        with pytest.raises(VaultPathError):
            call()
    vault.write_atomic("Inbox/s.pdf", b"S")
    sha = vault.sha256("Inbox/s.pdf")
    for through_a_file in (
        lambda: vault.read_bytes("Home/f/inside"),
        lambda: vault.write_atomic("Home/f/inside", b"x"),
        lambda: vault.copy_verified("Inbox/s.pdf", "Home/f/inside", sha),
        lambda: vault.unlink("Home/f/inside"),
    ):
        with pytest.raises(VaultGone):
            through_a_file()
    with pytest.raises(VaultPathError):
        vault.mkdirs("Home/f/inside")
    assert not vault.exists("Inbox/copy")
    assert {e.name for e in vault.list_dir("Inbox")} == {"pipe", "s.pdf"}


def test_a_symlink_counts_as_a_taken_name(vault: VaultRoot, tmp_path: Path) -> None:
    (vault.root / "Home" / "ln").symlink_to(tmp_path)
    assert vault.exists("Home/ln")
    assert vault.free_name("Home", "ln") == "ln (2)"


def test_from_settings_builds_the_root(tmp_path: Path) -> None:
    from household_vault.config import load_settings

    s = load_settings(env={"VAULT_ROOT": str(tmp_path / "v")})
    assert VaultRoot.from_settings(s).root == (tmp_path / "v").resolve()


@pytest.mark.skipif(sys.platform != "darwin", reason="needs O_NOFOLLOW_ANY, macOS only")
def test_a_folder_swapped_for_a_link_refuses_writes(
    vault: VaultRoot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "out"
    out.mkdir()
    vault.mkdirs("Home/one")
    vault.mkdirs("Home/two")
    vault.write_atomic("Inbox/s.pdf", b"S")
    sha = vault.sha256("Inbox/s.pdf")
    real = VaultRoot.path

    def racy(self: VaultRoot, r: str) -> Path:
        p = real(self, r)
        folder = p.parent
        if folder.name in ("one", "two") and not folder.is_symlink():
            folder.rename(folder.with_name(folder.name + ".real"))
            folder.symlink_to(out, target_is_directory=True)
        return p

    monkeypatch.setattr(VaultRoot, "path", racy)
    with pytest.raises(VaultPathError) as first:
        vault.write_atomic("Home/one/x.pdf", b"x")
    with pytest.raises(VaultPathError) as second:
        vault.copy_verified("Inbox/s.pdf", "Home/two/y.pdf", sha)
    assert not isinstance(first.value, VaultGone)
    assert not isinstance(second.value, VaultGone)
    assert list(out.iterdir()) == []


@pytest.mark.skipif(sys.platform != "darwin", reason="renamex_np is macOS only")
def test_rename_noreplace_is_atomic_without_the_exists_check(
    vault: VaultRoot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault.write_atomic("Inbox/a", b"A")
    vault.write_atomic("Home/a", b"USER")
    (vault.root / "Home" / "dl").symlink_to(tmp_path / "nowhere")
    monkeypatch.setattr(os.path, "lexists", lambda p: False)
    monkeypatch.setattr(os, "rename", raise_(AssertionError("fallback rename used")))
    src = vault.root / "Inbox" / "a"
    for taken in ("a", "dl"):
        with pytest.raises(FileExistsError):
            vr._rename_noreplace(src, vault.root / "Home" / taken)
    vr._rename_noreplace(src, vault.root / "Home" / "free")
    assert (vault.root / "Home" / "free").read_bytes() == b"A"
    assert (vault.root / "Home" / "a").read_bytes() == b"USER"


def test_a_folder_at_a_reserved_name_is_a_path_error(vault: VaultRoot) -> None:
    (vault.root / "Home" / ".x.pdf.tmp").mkdir()
    (vault.root / "Home" / ".y.pdf.partial").mkdir()
    vault.write_atomic("Inbox/y.pdf", b"y")
    with pytest.raises(VaultPathError, match="reserved"):
        vault.write_atomic("Home/x.pdf", b"x")
    with pytest.raises(VaultPathError, match="reserved"):
        vault.copy_verified("Inbox/y.pdf", "Home/y.pdf", vault.sha256("Inbox/y.pdf"))


def test_free_name_stays_within_the_name_limit(vault: VaultRoot) -> None:
    for name in ("a" * 239 + ".pdf", "\u00e9" * 119 + "a.pdf"):
        assert len(name.encode()) == 243
        vault.write_atomic(f"Home/{name}", b"x")
        free = vault.free_name("Home", name)
        assert len(free.encode()) <= MAX_NAME_BYTES
        assert free.endswith(" (2).pdf")
        assert not vault.exists(f"Home/{free}")
        vault.write_atomic(f"Home/{free}", b"y")
        assert vault.free_name("Home", name).endswith(" (3).pdf")
