"""The KeePass file: `Secrets.kdbx` in the vault, KDBX4 with Argon2, opened with the master
password (ADR 0004).

The file is read with `VaultRoot.read_bytes` and saved with `VaultRoot.write_atomic`, so no
other code path touches it, and a stop in the middle of a save leaves the old file. Only the app
on the Mac writes it. Before every change the store checks whether the file changed since it
was read (another KeePass app saved it) and builds on the file as it is now.

Nothing here puts a secret in a message, a repr or a log. `Cards` holds one entry per card with
the number and CVV as protected fields and the photos as protected attachments. `Documents`
holds the passwords of locked PDFs.
"""

from __future__ import annotations

import hmac
import io
import threading
import uuid
from collections.abc import Sequence
from typing import Any, Literal

from pykeepass import PyKeePass, create_database

from household_vault.vaultroot import SECRETS_FILE, VaultGone, VaultPathError, VaultRoot

Group = Literal["Cards", "Documents"]
GROUPS: tuple[Group, ...] = ("Cards", "Documents")
_OPEN_FAILED = "The secrets file could not be opened. Check the master password."


class SecretsLocked(Exception):
    """The master password is wrong, the file is missing or damaged, or the gate is closed.
    The message is shown to the owner as it is and never holds a secret."""


_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(vault: VaultRoot) -> threading.RLock:
    """One lock per secrets file, shared by every `SecretsStore` on it, so two writers never
    interleave a read, a change and a save."""
    key = str(vault.path(SECRETS_FILE))
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


def _parse(data: bytes, master_password: str) -> Any:
    try:
        return PyKeePass(io.BytesIO(data), password=master_password)
    except Exception:  # pykeepass and its parser raise several types; none is shown
        raise SecretsLocked(_OPEN_FAILED) from None


class SecretsStore:
    """An open `Secrets.kdbx`. Make one with `create` or `open`."""

    def __init__(self, vault: VaultRoot, kp: Any, snapshot: bytes) -> None:
        self._vault = vault
        self._kp = kp
        self._snapshot = snapshot
        self._lock = _lock_for(vault)

    def __repr__(self) -> str:
        return "SecretsStore()"

    # -- opening -------------------------------------------------------------------------------

    @classmethod
    def create(cls, vault: VaultRoot, master_password: str) -> SecretsStore:
        """A new KDBX4 file with the two groups. Refuses to touch a file that exists."""
        with _lock_for(vault):
            if vault.exists(SECRETS_FILE):
                raise FileExistsError("the secrets file already exists")
            buf = io.BytesIO()
            kp = create_database(buf, password=master_password)
            for name in GROUPS:
                kp.add_group(kp.root_group, name)
            store = cls(vault, kp, b"")
            store._save()
            return store

    @classmethod
    def open(cls, vault: VaultRoot, master_password: str) -> SecretsStore:
        with _lock_for(vault):
            try:
                data = vault.read_bytes(SECRETS_FILE)
            except VaultPathError:  # missing, a link, a folder
                raise SecretsLocked("There is no secrets file yet.") from None
            return cls(vault, _parse(data, master_password), data)

    def password_matches(self, master_password: str) -> bool:
        """True when this open store was opened with that password (constant time)."""
        return hmac.compare_digest(str(self._kp.password).encode(), master_password.encode())

    @property
    def version(self) -> tuple[int, int]:
        major, minor = self._kp.version
        return (int(major), int(minor))

    # -- reading -------------------------------------------------------------------------------

    def entries(self, group: Group) -> list[str]:
        """The UUIDs of a group's entries, oldest first."""
        with self._lock:
            return [str(e.uuid) for e in self._group(group).entries]

    def has_entry(self, uid: str) -> bool:
        with self._lock:
            return self._find(uid) is not None

    def entry_fields(self, uid: str) -> dict[str, str]:
        """`title`, every custom field (`number`, `cvv`, `expiry`, `holder`) and, when it has
        one, `password`."""
        with self._lock:
            entry = self._entry(uid)
            fields: dict[str, str] = {"title": entry.title or ""}
            fields.update({k: v for k, v in entry.custom_properties.items() if v is not None})
            if entry.password:
                fields["password"] = entry.password
            return fields

    def attachment_names(self, uid: str) -> list[str]:
        with self._lock:
            return [a.filename for a in self._entry(uid).attachments]

    def attachment(self, uid: str, name: str) -> bytes:
        with self._lock:
            for a in self._entry(uid).attachments:
                if a.filename == name:
                    data: bytes = a.binary
                    return data
        raise KeyError(name)

    # -- writing -------------------------------------------------------------------------------

    def add_card(
        self,
        title: str,
        number: str,
        expiry: str | None,
        cvv: str | None,
        holder: str | None,
        photos: Sequence[tuple[str, bytes]],
        uid: str | None = None,
    ) -> str:
        """Add a card and save. The number and CVV are protected fields and the photos are
        protected attachments. With `uid` the entry gets that UUID (made and remembered by the
        caller first, so a stop after the save is found again); an entry that already has it is
        returned as it is. Returns the entry's UUID."""
        with self._lock:
            self._refresh()
            if uid is not None and self._find(uid) is not None:
                return uid
            entry = self._kp.add_entry(self._group("Cards"), title, "", "", force_creation=True)
            if uid is not None:
                entry.uuid = uuid.UUID(uid)
            entry.set_custom_property("number", number, protect=True)
            if cvv:
                entry.set_custom_property("cvv", cvv, protect=True)
            if expiry:
                entry.set_custom_property("expiry", expiry)
            if holder:
                entry.set_custom_property("holder", holder)
            for name, data in photos:
                entry.add_attachment(self._kp.add_binary(data, protected=True), name)
            uid = str(entry.uuid)
            self._save()
            return uid

    def add_pdf_password(self, title: str, password: str) -> str:
        """Add the password of a locked PDF and save. The same title and password again
        returns the entry that is there."""
        with self._lock:
            self._refresh()
            group = self._group("Documents")
            for entry in group.entries:
                if entry.title == title and entry.password == password:
                    return str(entry.uuid)
            entry = self._kp.add_entry(group, title, "", password, force_creation=True)
            uid = str(entry.uuid)
            self._save()
            return uid

    # -- inside --------------------------------------------------------------------------------

    def _group(self, name: Group) -> Any:
        group = self._kp.find_groups(name=name, first=True)
        if group is None:
            group = self._kp.add_group(self._kp.root_group, name)
        return group

    def _find(self, uid: str) -> Any | None:
        try:
            key = uuid.UUID(uid)
        except ValueError:
            return None
        return self._kp.find_entries(uuid=key, first=True)

    def _entry(self, uid: str) -> Any:
        entry = self._find(uid)
        if entry is None:
            raise KeyError("no such entry")
        return entry

    def _refresh(self) -> None:
        """Build on the file as it is now when another program saved it since it was read."""
        try:
            current = self._vault.read_bytes(SECRETS_FILE)
        except VaultPathError:
            raise SecretsLocked("The secrets file is not there any more.") from None
        if current != self._snapshot:
            self._kp = _parse(current, self._kp.password)
            self._snapshot = current

    def _save(self) -> None:
        buf = io.BytesIO()
        self._kp.save(buf)
        data = buf.getvalue()
        try:
            self._vault.write_atomic(SECRETS_FILE, data)
        except BaseException:
            # The file is as it was; put the memory copy back to match it.
            if self._snapshot:
                self._kp = _parse(self._snapshot, self._kp.password)
            raise
        self._snapshot = data


__all__ = ["GROUPS", "Group", "SecretsLocked", "SecretsStore", "VaultGone"]
