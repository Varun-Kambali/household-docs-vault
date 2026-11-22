"""Show a filed document in Finder, on the Mac the app runs on."""

import subprocess
from pathlib import Path
from typing import Protocol

TIMEOUT_SECONDS = 5


class RevealFailed(Exception):
    """Finder did not open: `open` timed out, could not run or exited with an error. The message
    never reaches a response."""


class Revealer(Protocol):
    def reveal(self, path: Path) -> None: ...


class MacRevealer:
    """`open -R` selects the file in a Finder window. The path is one argument, never a shell
    string."""

    def reveal(self, path: Path) -> None:
        try:
            done = subprocess.run(["open", "-R", str(path)], check=False, timeout=TIMEOUT_SECONDS)
        except (subprocess.TimeoutExpired, OSError):
            raise RevealFailed("open did not finish") from None
        if done.returncode != 0:
            raise RevealFailed("open failed")
