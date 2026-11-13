"""Guards that keep tools off the real vault and off cloud-synced folders."""

import contextlib
import os
import pwd
from pathlib import Path

# macOS exposes the data volume under this prefix as well (an APFS firmlink), and resolve() does
# not rewrite it, so "/System/Volumes/Data/Users/me" and "/Users/me" are the same folder.
_FIRMLINK = "/System/Volumes/Data"

_BLOCKED_UNDER_HOME = (
    "Library/CloudStorage",
    "Library/Application Support/household-vault",
    "Library/Application Support/Google/DriveFS",
)


class UnsafePathError(ValueError):
    """The path points at real documents or at a cloud-synced folder."""


def _homes() -> list[Path]:
    homes = [Path(os.path.expanduser("~"))]
    with contextlib.suppress(KeyError):
        homes.append(Path(pwd.getpwuid(os.getuid()).pw_dir))
    seen: list[Path] = []
    for home in homes:
        if home not in seen:
            seen.append(home)
    return seen


def _blocked_roots() -> list[Path]:
    roots = [home / rel for home in _homes() for rel in _BLOCKED_UNDER_HOME]
    real_root = os.environ.get("VAULT_REAL_ROOT")
    if real_root:
        roots.append(Path(real_root).expanduser())
    return [root.resolve() for root in roots]


def _fold(path: Path) -> Path:
    text = str(path)
    if text == _FIRMLINK or text.startswith(_FIRMLINK + "/"):
        text = text[len(_FIRMLINK) :] or "/"
    # Case-fold: the Mac's default APFS ignores case, so "library/cloudstorage" is the same folder.
    return Path(text.casefold())


def _same_file(a: Path, b: Path) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def assert_safe_path(path: Path) -> Path:
    # resolve() first so "..", symlinks and relative paths cannot sneak past the prefix check
    resolved = path.expanduser().resolve()
    blocked = _blocked_roots()
    folded = _fold(resolved)
    for root in blocked:
        if folded.is_relative_to(_fold(root)):
            raise UnsafePathError(f"refusing to touch {resolved}: it is under {root}")
    # Filesystem identity catches spellings the string test cannot (firmlinks, bind-like aliases):
    # the target or any existing ancestor that is the same folder as a blocked root is refused.
    existing = [root for root in blocked if root.exists()]
    if existing:
        for candidate in (resolved, *resolved.parents):
            if not candidate.exists():
                continue
            for root in existing:
                if _same_file(candidate, root):
                    raise UnsafePathError(f"refusing to touch {resolved}: it is under {root}")
    return resolved
