from pathlib import Path

import pytest

from household_vault.intake.watcher import IGNORED, Settler, inbox_listing
from household_vault.vaultroot import VaultRoot
from tests.conftest import FakeClock


def test_settler_waits_for_a_steady_file_and_starts_over_when_it_vanishes() -> None:
    clock = FakeClock(0.0)
    s = Settler(10.0, clock)
    steps = [
        (0, {"a.pdf": (10, 1)}, []),
        (5, {"a.pdf": (20, 2)}, []),
        (16, {"a.pdf": (20, 2)}, ["a.pdf"]),
        (17, {}, []),
        (20, {"a.pdf": (20, 2)}, []),
        (31, {"a.pdf": (20, 2)}, ["a.pdf"]),
    ]
    for t, listing, ready in steps:
        clock.t = t
        assert s.ready(listing) == ready, t


def test_settle_zero_is_ready_when_first_seen() -> None:
    s = Settler(0, FakeClock(5.0))
    assert s.ready({"b.pdf": (1, 1), "a.pdf": (1, 1)}) == ["a.pdf", "b.pdf"]


def test_ready_stays_returned_while_it_holds() -> None:
    clock = FakeClock(0.0)
    s = Settler(1.0, clock)
    s.ready({"a.pdf": (1, 1)})
    clock.t = 2
    assert s.ready({"a.pdf": (1, 1)}) == ["a.pdf"]
    assert s.ready({"a.pdf": (1, 1)}) == ["a.pdf"]


def test_listing_skips_temp_hidden_folders_and_symlinks(vault: VaultRoot, tmp_path: Path) -> None:
    for name in ("a.pdf", ".hidden.pdf", "b.pdf.crdownload", "~$c.pdf"):
        vault.write_atomic(f"Inbox/{name}", b"x")
    vault.mkdirs("Inbox/sub")
    (vault.root / "Inbox" / "link.pdf").symlink_to(tmp_path / "victim")
    assert set(inbox_listing(vault)) == {"a.pdf"}
    assert inbox_listing(vault)["a.pdf"][0] == 1


@pytest.mark.parametrize("name", ["x.tmp", "x.partial", "x.part", "x.download", ".x", "~$x"])
def test_ignored_names(name: str) -> None:
    assert IGNORED(name)
