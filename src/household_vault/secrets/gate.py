"""The unlock gate: the master password opens the store for 10 minutes, in memory only.

The gate keeps the open store, which holds the master password inside its KeePass object, and
nothing else. After the time is up, or after `lock`, the store is let go. The password is never
written to a file, the database or a log (D-010).
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from household_vault.secrets.store import SecretsLocked, SecretsStore
from household_vault.vaultroot import VaultRoot

UNLOCK_SECONDS = 600.0


class SecretsGate:
    def __init__(
        self,
        vault: VaultRoot,
        clock: Callable[[], float],
        unlock_seconds: float = UNLOCK_SECONDS,
    ) -> None:
        self._vault = vault
        self._clock = clock
        self._seconds = unlock_seconds
        self._store: SecretsStore | None = None
        self._until = 0.0
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return "SecretsGate()"

    def unlock(self, master_password: str) -> None:
        """Open the store with the master password. A wrong one raises `SecretsLocked`."""
        self._hold(SecretsStore.open(self._vault, master_password))

    def create(self, master_password: str) -> None:
        """Make the secrets file and leave it open."""
        self._hold(SecretsStore.create(self._vault, master_password))

    def is_open(self) -> bool:
        with self._lock:
            return self._current() is not None

    def store(self) -> SecretsStore:
        with self._lock:
            store = self._current()
        if store is None:
            raise SecretsLocked("The secrets store is locked. Enter the master password.")
        return store

    def lock(self) -> None:
        with self._lock:
            self._store = None

    def _hold(self, store: SecretsStore) -> None:
        with self._lock:
            self._store = store
            self._until = self._clock() + self._seconds

    def _current(self) -> SecretsStore | None:
        """The store while the time is not up; else it is let go. Call with the lock held."""
        if self._store is not None and self._clock() > self._until:
            self._store = None
        return self._store
