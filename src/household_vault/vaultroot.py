"""The vault root: the only door through which `src` touches vault files.

Every path is a `/`-separated string relative to the root. A path is checked part by part, no
part may be a symlink, and every open uses O_NOFOLLOW, so a link dropped into the vault (or a
path built from document text) cannot lead a read or a write outside it.
"""

import contextlib
import errno
import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from household_vault.safety import assert_safe_path

INBOX = "Inbox"
NEEDS_A_LOOK = "Needs a look"
RECORDS = "_system/records"
LOGS = "_system/log"
BACKUP = "_system/backup"
SECRETS_FILE = "Secrets.kdbx"

_CHUNK = 1024 * 1024
# Where a hard link is not possible (some cloud-sync folders): fall back to a checked rename.
_NO_LINK = (errno.EPERM, errno.ENOTSUP, errno.EXDEV)


class VaultPathError(ValueError):
    """A path the vault refuses: an escape, a bad name or a symlink."""


class CopyMismatch(VaultPathError):
    """A copy whose SHA-256 differs from the one expected for the source."""


class VaultGone(VaultPathError):
    """The path does not exist, for example a file that vanished while it was being read."""


@dataclass(frozen=True)
class Entry:
    name: str
    kind: Literal["file", "dir", "symlink", "other"]
    size: int
    mtime_ns: int


def check_component(name: str) -> str:
    """Return name if it is one safe path part, else raise VaultPathError."""
    if name in ("", ".", ".."):
        raise VaultPathError(f"not a usable name: {name!r}")
    if "/" in name or "\\" in name:
        raise VaultPathError(f"a name cannot contain a slash: {name!r}")
    if any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise VaultPathError("a name cannot contain control characters")
    return name


def _gone(rel: str) -> VaultGone:
    return VaultGone(f"no such file or folder in the vault: {rel}")


def _no_link(rel: str) -> VaultPathError:
    return VaultPathError(f"refusing a symbolic link in the vault: {rel}")


class VaultRoot:
    def __init__(self, root: Path, *, mode: Literal["dev", "app"]) -> None:
        self.mode = mode
        self.root: Path = assert_safe_path(root) if mode == "dev" else root.expanduser().resolve()

    # -- paths ---------------------------------------------------------------------------------

    def _parts(self, rel: str) -> list[str]:
        if not rel or rel.startswith("/"):
            raise VaultPathError(f"a vault path is relative and not empty: {rel!r}")
        return [check_component(part) for part in rel.split("/")]

    def _resolve(self, rel: str, *, final_link_ok: bool = False) -> Path:
        parts = self._parts(rel)
        current = self.root
        for i, part in enumerate(parts):
            current = current / part
            try:
                mode = os.lstat(current).st_mode
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(mode) and not (final_link_ok and i == len(parts) - 1):
                raise _no_link(rel)
        if not current.resolve().is_relative_to(self.root) and not final_link_ok:
            raise VaultPathError(f"path leaves the vault: {rel}")
        return current

    def path(self, rel: str) -> Path:
        """The absolute path of rel, or VaultPathError if it escapes or crosses a symlink."""
        return self._resolve(rel)

    def exists(self, rel: str) -> bool:
        return os.path.lexists(self.path(rel))

    # -- reading -------------------------------------------------------------------------------

    def _open_read(self, rel: str) -> int:
        target = self.path(rel)
        try:
            return os.open(target, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            raise _gone(rel) from None
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise _no_link(rel) from None
            raise

    def list_dir(self, rel: str) -> list[Entry]:
        folder = self.path(rel)
        entries: list[Entry] = []
        try:
            with os.scandir(folder) as it:
                for item in it:
                    try:
                        st = item.stat(follow_symlinks=False)
                    except FileNotFoundError:
                        continue
                    if stat.S_ISLNK(st.st_mode):
                        kind: Literal["file", "dir", "symlink", "other"] = "symlink"
                    elif stat.S_ISREG(st.st_mode):
                        kind = "file"
                    elif stat.S_ISDIR(st.st_mode):
                        kind = "dir"
                    else:
                        kind = "other"
                    entries.append(Entry(item.name, kind, st.st_size, st.st_mtime_ns))
        except (FileNotFoundError, NotADirectoryError):
            raise _gone(rel) from None
        return sorted(entries, key=lambda e: e.name)

    def read_bytes(self, rel: str) -> bytes:
        fd = self._open_read(rel)
        with os.fdopen(fd, "rb") as fh:
            return fh.read()

    def sha256(self, rel: str) -> str:
        digest = hashlib.sha256()
        fd = self._open_read(rel)
        with os.fdopen(fd, "rb") as fh:
            while chunk := fh.read(_CHUNK):
                digest.update(chunk)
        return digest.hexdigest()

    # -- writing -------------------------------------------------------------------------------

    def _sibling(self, target: Path, suffix: str) -> Path:
        return target.with_name(f".{target.name}{suffix}")

    def _create_exclusive(self, path: Path, rel: str) -> int:
        # A leftover from an earlier stop is ours to replace; a link planted there is removed
        # as a link and never followed.
        with contextlib.suppress(FileNotFoundError):
            os.unlink(path)
        try:
            return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileNotFoundError:
            raise _gone(rel) from None

    def write_atomic(self, rel: str, data: bytes) -> None:
        target = self.path(rel)
        tmp = self._sibling(target, ".tmp")
        fd = self._create_exclusive(tmp, rel)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, target)
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp)

    def append_text(self, rel: str, text: str) -> None:
        target = self.path(rel)
        try:
            fd = os.open(target, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        except FileNotFoundError:
            raise _gone(rel) from None
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise _no_link(rel) from None
            raise
        with os.fdopen(fd, "a", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())

    def _place(self, source: Path, dst: Path, dst_rel: str) -> None:
        """Make dst appear as a new name for source without ever replacing a file."""
        try:
            os.link(source, dst)
        except FileExistsError:
            raise
        except FileNotFoundError:
            raise _gone(dst_rel) from None
        except OSError as exc:
            if exc.errno not in _NO_LINK:
                raise
            if os.path.lexists(dst):
                raise FileExistsError(errno.EEXIST, "already exists", str(dst)) from None
            os.rename(source, dst)

    def copy_verified(self, src: str, dst: str, sha256: str) -> None:
        self.path(src)
        target = self.path(dst)
        if os.path.lexists(target):
            raise FileExistsError(errno.EEXIST, "already exists", dst)
        partial = self._sibling(target, ".partial")
        digest = hashlib.sha256()
        in_fd = self._open_read(src)
        try:
            with os.fdopen(in_fd, "rb") as reader:
                out_fd = self._create_exclusive(partial, dst)
                with os.fdopen(out_fd, "wb") as writer:
                    while chunk := reader.read(_CHUNK):
                        digest.update(chunk)
                        writer.write(chunk)
                    writer.flush()
                    os.fsync(writer.fileno())
            if digest.hexdigest() != sha256:
                raise CopyMismatch(f"the copy of {src} does not match the expected SHA-256")
            self._place(partial, target, dst)
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(partial)

    def move(self, src: str, dst: str) -> None:
        source = self.path(src)
        target = self.path(dst)
        if not os.path.lexists(source):
            raise _gone(src)
        self._place(source, target, dst)
        # After a rename fallback the source name is already gone.
        with contextlib.suppress(FileNotFoundError):
            os.unlink(source)

    def unlink(self, rel: str) -> None:
        target = self._resolve(rel, final_link_ok=True)
        try:
            os.unlink(target)
        except FileNotFoundError:
            raise _gone(rel) from None

    def mkdirs(self, rel: str) -> None:
        parts = self._parts(rel)
        if self.mode == "dev":
            self.root.mkdir(parents=True, exist_ok=True)
        for i in range(1, len(parts) + 1):
            folder = self.path("/".join(parts[:i]))
            if not os.path.lexists(folder):
                try:
                    os.mkdir(folder)
                except FileNotFoundError:
                    raise _gone(rel) from None
            elif not folder.is_dir():
                raise VaultPathError(f"not a folder: {'/'.join(parts[:i])}")

    def free_name(self, folder: str, name: str) -> str:
        """A file name in folder that is not taken: name, then `stem (2).ext`, `stem (3).ext`."""
        check_component(name)
        if not self.exists(f"{folder}/{name}"):
            return name
        stem, dot, ext = name.rpartition(".")
        if not dot or not stem:
            stem, ext = name, ""
        else:
            ext = "." + ext
        n = 2
        while self.exists(f"{folder}/{stem} ({n}){ext}"):
            n += 1
        return f"{stem} ({n}){ext}"
