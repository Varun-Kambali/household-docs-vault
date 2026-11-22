"""Show a filed document in Finder, on the Mac the app runs on."""

import subprocess
from pathlib import Path
from typing import Protocol


class Revealer(Protocol):
    def reveal(self, path: Path) -> None: ...


class MacRevealer:
    """`open -R` selects the file in a Finder window. The path is one argument, never a shell
    string."""

    def reveal(self, path: Path) -> None:
        subprocess.run(["open", "-R", str(path)], check=False, timeout=10)
