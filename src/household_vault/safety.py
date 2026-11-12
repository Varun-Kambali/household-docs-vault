"""Guards that keep tools off the real vault and off cloud-synced folders."""

import os
from pathlib import Path


class UnsafePathError(ValueError):
    """The path points at real documents or at a cloud-synced folder."""


def assert_safe_path(path: Path) -> Path:
    # resolve() first so "..", symlinks and relative paths cannot sneak past the prefix check
    resolved = path.expanduser().resolve()
    blocked = [(Path.home() / "Library" / "CloudStorage").resolve()]
    real_root = os.environ.get("VAULT_REAL_ROOT")
    if real_root:
        blocked.append(Path(real_root).expanduser().resolve())
    for root in blocked:
        if resolved == root or resolved.is_relative_to(root):
            raise UnsafePathError(f"refusing to touch {resolved}: it is under {root}")
    return resolved
