"""HEIC photos from an iPhone become PNG through macOS's own `sips`."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from household_vault.reading.ocr import EngineUnavailable
from household_vault.reading.render import DamagedFileError

SIPS = "/usr/bin/sips"


def heic_to_png(data: bytes) -> bytes:
    if sys.platform != "darwin":
        raise EngineUnavailable("HEIC photos can be read on macOS only")
    folder = Path(tempfile.mkdtemp(prefix="vault-heic-"))  # mode 0700, private to this user
    try:
        src, out = folder / "in.heic", folder / "out.png"
        src.write_bytes(data)
        subprocess.run(
            [SIPS, "-s", "format", "png", str(src), "--out", str(out)],
            check=False,
            capture_output=True,
            timeout=60,
        )
        if not out.exists():
            raise DamagedFileError("the photo could not be converted")
        return out.read_bytes()
    finally:
        shutil.rmtree(folder, ignore_errors=True)
