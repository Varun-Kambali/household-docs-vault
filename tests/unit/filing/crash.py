"""Hard-stop emulation for the filer tests.

`Killed` is a BaseException. `Kill` raises it at a chosen call and, from then on, makes every
write at the operating-system level (unlink, rename, link, replace, mkdir) raise it too, so a
`finally` clean-up cannot run, as when the process dies. SQLite rolls back an open transaction
either way. `no_links` makes hard links fail the way Google Drive's folders do.
"""

import errno
import hashlib
import os
from collections.abc import Callable
from typing import Any

import pytest

from household_vault.activity import Activity
from household_vault.filing.filer import Filer
from household_vault.vaultroot import VaultRoot
from tests.unit.filing.samples import NOW


class Killed(BaseException):
    pass


class Kill:
    def __init__(self, mp: pytest.MonkeyPatch) -> None:
        self.dead = False
        self.mp = mp
        for name in ("unlink", "rename", "link", "replace", "mkdir"):
            mp.setattr(os, name, self._guard(getattr(os, name)))

    def _guard(self, real: Callable[..., Any]) -> Callable[..., Any]:
        def guarded(*a: Any, **k: Any) -> Any:
            if self.dead:
                raise Killed
            return real(*a, **k)

        return guarded

    def now(self) -> None:
        self.dead = True
        raise Killed

    def before(self, obj: object, name: str, nth: int = 1) -> None:
        real = getattr(obj, name)
        count = {"n": 0}

        def wrapper(*a: Any, **k: Any) -> Any:
            count["n"] += 1
            if count["n"] == nth:
                self.now()
            return real(*a, **k)

        self.mp.setattr(obj, name, wrapper)

    def after(self, obj: object, name: str, nth: int = 1) -> None:
        real = getattr(obj, name)
        count = {"n": 0}

        def wrapper(*a: Any, **k: Any) -> Any:
            out = real(*a, **k)
            count["n"] += 1
            if count["n"] == nth:
                self.now()
            return out

        self.mp.setattr(obj, name, wrapper)


def no_links(mp: pytest.MonkeyPatch) -> None:
    def refuse(*a: Any, **k: Any) -> None:
        raise OSError(errno.ENOTSUP, "no hard links")

    mp.setattr(os, "link", refuse)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def all_files(vault: VaultRoot, rel: str = "") -> list[str]:
    base = vault.root / rel if rel else vault.root
    out = []
    for folder, _, names in os.walk(base):
        for name in names:
            out.append(os.path.relpath(os.path.join(folder, name), vault.root))
    return sorted(out)


def user_files(vault: VaultRoot) -> list[str]:
    return [p for p in all_files(vault) if not p.startswith("_system/")]


def records_on_disk(vault: VaultRoot) -> list[str]:
    return all_files(vault, "_system/records") if vault.exists("_system/records") else []


def hidden_files(vault: VaultRoot) -> list[str]:
    return [p for p in all_files(vault) if p.rsplit("/", 1)[-1].startswith(".")]


def fresh_filer(vault: VaultRoot, store: Any, household: Any) -> Filer:
    """A second Filer on the same files and database, as after a restart."""
    return Filer(vault, store, Activity(store, vault, lambda: NOW), household, lambda: NOW)
