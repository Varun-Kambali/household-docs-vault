"""Watch Inbox by polling: list it, and report the files that have stopped changing."""

from collections.abc import Callable, Mapping

from household_vault.vaultroot import INBOX, VaultRoot

_IGNORED_PREFIXES = (".", "~$")
_IGNORED_SUFFIXES = (".tmp", ".partial", ".part", ".crdownload", ".download")


def IGNORED(name: str) -> bool:
    """True for hidden files, Office lock files and the temporary names syncing leaves."""
    return name.startswith(_IGNORED_PREFIXES) or name.lower().endswith(_IGNORED_SUFFIXES)


def inbox_listing(vault: VaultRoot) -> dict[str, tuple[int, int]]:
    """Regular files directly in Inbox: name to (size, mtime_ns)."""
    return {
        e.name: (e.size, e.mtime_ns)
        for e in vault.list_dir(INBOX)
        if e.kind == "file" and not IGNORED(e.name)
    }


class Settler:
    """Reports names whose size and modification time have held for `settle_seconds`."""

    def __init__(self, settle_seconds: float, clock: Callable[[], float]) -> None:
        self.settle_seconds = settle_seconds
        self.clock = clock
        self._seen: dict[str, tuple[tuple[int, int], float]] = {}

    def ready(self, listing: Mapping[str, tuple[int, int]]) -> list[str]:
        now = self.clock()
        seen: dict[str, tuple[tuple[int, int], float]] = {}
        for name, sig in listing.items():
            before = self._seen.get(name)
            seen[name] = before if before is not None and before[0] == sig else (sig, now)
        self._seen = seen
        return sorted(n for n, (_, since) in seen.items() if now - since >= self.settle_seconds)
