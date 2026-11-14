"""The vault root: the only door through which `src` touches vault files.

Every path is a `/`-separated string relative to the root. Threat model: paths are checked
component by component (no `..`, no control characters, no symlink on the way, the result stays
under the root) and every open refuses symlinks, anywhere in the path on macOS. That covers
names built from document text and links dropped into the vault by Drive or the phone. A
process running as the owner can still race a folder swap between the check and the open; this
app does not defend against that, because such a process already has the owner's access.

Files are never replaced by a copy or a move: they land through a hard link, or where the
folder refuses hard links (some cloud-sync folders), through a no-replace rename. The names
`.<name>.tmp` and `.<name>.partial` beside a target are reserved for atomic writes and copies;
a leftover from an earlier stop is replaced, and a link planted there is removed, not followed.
"""

import contextlib
import ctypes
import errno
import fcntl
import hashlib
import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from household_vault.safety import assert_safe_path

if TYPE_CHECKING:
    from household_vault.config import Settings

INBOX = "Inbox"
NEEDS_A_LOOK = "Needs a look"
RECORDS = "_system/records"
LOGS = "_system/log"
BACKUP = "_system/backup"
SECRETS_FILE = "Secrets.kdbx"

# A file name is at most 255 UTF-8 bytes; copies add ".<name>.partial" (a dot and ".partial").
MAX_NAME_BYTES = 246

_CHUNK = 1024 * 1024
# O_NOFOLLOW_ANY (macOS) refuses a link anywhere in the path; it replaces O_NOFOLLOW, and the two
# flags cannot be combined.
_NOFOLLOW = getattr(os, "O_NOFOLLOW_ANY", os.O_NOFOLLOW)
_RENAME_EXCL = 0x00000004
_BIDI_CONTROLS = frozenset(
    {
        0x200E,
        0x200F,
        *range(0x202A, 0x202F),
        *range(0x2066, 0x206A),
    }  # LRM, RLM, embeddings, isolates
)


class VaultPathError(ValueError):
    """A path the vault refuses: an escape, a bad name, a symlink or not a regular file."""


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
    for c in name:
        n = ord(c)
        if n < 32 or 0x7F <= n <= 0x9F or n in _BIDI_CONTROLS:
            raise VaultPathError("a name cannot contain control characters")
    try:
        size = len(name.encode("utf-8"))
    except UnicodeEncodeError:
        raise VaultPathError("a name must be valid text") from None
    if size > MAX_NAME_BYTES:
        raise VaultPathError(f"a name is at most {MAX_NAME_BYTES} bytes in UTF-8, got {size}")
    return name


def _gone(rel: str) -> VaultGone:
    return VaultGone(f"no such file or folder in the vault: {rel}")


def _no_link(rel: str) -> VaultPathError:
    return VaultPathError(f"refusing a symbolic link in the vault: {rel}")


def _sync_file(fd: int) -> None:
    """Flush a file to the disk itself; on macOS plain fsync stops at the drive's cache."""
    full = getattr(fcntl, "F_FULLFSYNC", None)
    if full is not None:
        try:
            fcntl.fcntl(fd, full)
        except OSError:
            os.fsync(fd)
        else:
            return
    else:
        os.fsync(fd)


def _sync_dir(folder: Path) -> None:
    """Make a rename, link or unlink in folder durable. Best effort: some folders refuse it."""
    with contextlib.suppress(OSError):
        fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _rename_noreplace(src: Path, dst: Path) -> None:
    """Rename src to dst, raising FileExistsError instead of replacing dst."""
    if sys.platform == "darwin":
        libc = ctypes.CDLL(None, use_errno=True)
        renamex = libc.renamex_np
        renamex.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        if renamex(os.fsencode(src), os.fsencode(dst), _RENAME_EXCL) == 0:
            return
        err = ctypes.get_errno()
        if err == errno.EEXIST:
            raise FileExistsError(errno.EEXIST, "already exists", str(dst))
        if err not in (errno.ENOTSUP, errno.EINVAL):
            raise OSError(err, os.strerror(err), str(dst))
    if os.path.lexists(dst):
        raise FileExistsError(errno.EEXIST, "already exists", str(dst))
    os.rename(src, dst)


class VaultRoot:
    def __init__(self, root: Path, *, mode: Literal["dev", "app"]) -> None:
        self.mode = mode
        self.root: Path = assert_safe_path(root) if mode == "dev" else root.expanduser().resolve()

    @classmethod
    def from_settings(cls, settings: "Settings") -> "VaultRoot":
        return cls(settings.vault_root, mode=settings.mode)

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
            except (FileNotFoundError, NotADirectoryError):
                continue
            if stat.S_ISLNK(mode) and not (final_link_ok and i == len(parts) - 1):
                raise _no_link(rel)
        # A final link is allowed here (to unlink or to name a taken slot), so only the folder
        # holding it must be inside the root.
        checked = current.parent if final_link_ok else current
        if not checked.resolve().is_relative_to(self.root):
            raise VaultPathError(f"path leaves the vault: {rel}")
        return current

    def path(self, rel: str) -> Path:
        """The absolute path of rel, or VaultPathError if it escapes or crosses a symlink."""
        return self._resolve(rel)

    def exists(self, rel: str) -> bool:
        """True if the name is taken, including by a symlink or a broken one."""
        return os.path.lexists(self._resolve(rel, final_link_ok=True))

    # -- reading -------------------------------------------------------------------------------

    def _open_read(self, rel: str) -> int:
        target = self.path(rel)
        try:
            fd = os.open(target, os.O_RDONLY | _NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            raise _gone(rel) from None
        except NotADirectoryError:
            raise _gone(rel) from None
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise _no_link(rel) from None
            raise
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            os.close(fd)
            raise VaultPathError(f"not a regular file: {rel}")
        return fd

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
            return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW, 0o600)
        except (FileNotFoundError, NotADirectoryError):
            raise _gone(rel) from None

    def write_atomic(self, rel: str, data: bytes) -> None:
        target = self.path(rel)
        tmp = self._sibling(target, ".tmp")
        fd = self._create_exclusive(tmp, rel)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                _sync_file(fh.fileno())
            os.replace(tmp, target)
            _sync_dir(target.parent)
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp)

    def append_text(self, rel: str, text: str) -> None:
        target = self.path(rel)
        try:
            fd = os.open(target, os.O_WRONLY | os.O_APPEND | os.O_CREAT | _NOFOLLOW, 0o600)
        except (FileNotFoundError, NotADirectoryError):
            raise _gone(rel) from None
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise _no_link(rel) from None
            raise
        with os.fdopen(fd, "a", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            _sync_file(fh.fileno())

    def _place(self, source: Path, dst: Path, dst_rel: str) -> Literal["linked", "renamed"]:
        """Make dst appear as a new name for source without ever replacing a file.

        Returns "linked" when source still exists afterwards, "renamed" when it is gone.
        """
        try:
            os.link(source, dst, follow_symlinks=False)
            return "linked"
        except FileExistsError:
            raise
        except (FileNotFoundError, NotADirectoryError):
            raise _gone(dst_rel) from None
        except OSError:
            # Drive's File Provider folders refuse hard links, with an errno we cannot list.
            pass
        try:
            _rename_noreplace(source, dst)
        except (FileNotFoundError, NotADirectoryError):
            raise _gone(dst_rel) from None
        return "renamed"

    def copy_verified(self, src: str, dst: str, sha256: str) -> None:
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
                    _sync_file(writer.fileno())
            if digest.hexdigest() != sha256:
                raise CopyMismatch(f"the copy of {src} does not match the expected SHA-256")
            self._place(partial, target, dst)
            _sync_dir(target.parent)
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(partial)

    def move(self, src: str, dst: str) -> None:
        source = self.path(src)
        target = self.path(dst)
        if not os.path.lexists(source):
            raise _gone(src)
        if self._place(source, target, dst) == "linked":
            with contextlib.suppress(FileNotFoundError):
                os.unlink(source)
        _sync_dir(target.parent)
        _sync_dir(source.parent)

    def unlink(self, rel: str) -> None:
        target = self._resolve(rel, final_link_ok=True)
        try:
            os.unlink(target)
        except FileNotFoundError:
            raise _gone(rel) from None
        _sync_dir(target.parent)

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
                _sync_dir(folder.parent)
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
