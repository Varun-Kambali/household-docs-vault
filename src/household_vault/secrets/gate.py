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
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return "SecretsGate()"

    def unlock(self, master_password: str) -> None:
        """Open the store with the master password. A wrong one raises `SecretsLocked`."""
        with self._lock:
            held = self._current()
            if held is not None and held.password_matches(master_password):
                self._until = self._clock() + self._seconds  # same store, new ten minutes
                return
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
            self._stop_timer()

    def _hold(self, store: SecretsStore) -> None:
        with self._lock:
            self._store = store
            self._until = self._clock() + self._seconds
            self._start_timer(self._seconds)

    def _start_timer(self, delay: float) -> None:
        """Let go of the store when the time is up, even if nothing calls the gate again."""
        self._stop_timer()
        timer = threading.Timer(max(delay, 0.01), self._expire)
        timer.daemon = True
        self._timer = timer
        timer.start()

    def _stop_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _expire(self) -> None:
        with self._lock:
            if self._current() is not None:  # the clock says there is time left
                self._start_timer(self._until - self._clock())

    def _current(self) -> SecretsStore | None:
        """The store while the time is not up; else it is let go. Call with the lock held."""
        if self._store is not None and self._clock() > self._until:
            self._store = None
        return self._store
