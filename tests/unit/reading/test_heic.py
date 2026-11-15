import subprocess
import sys
from pathlib import Path

import pytest

from household_vault.reading import heic
from household_vault.reading.heic import heic_to_png
from household_vault.reading.ocr import EngineUnavailable


def fake_run(monkeypatch, writes_png):
    calls = []

    def run(cmd, **kwargs):
        calls.append(list(cmd))
        if writes_png:
            out = cmd[cmd.index("--out") + 1]
            Path(out).write_bytes(b"\x89PNG\r\n\x1a\nfake")
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(heic.subprocess, "run", run)
    return calls


def test_heic_goes_through_sips(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    calls = fake_run(monkeypatch, writes_png=True)
    assert heic_to_png(b"\x00\x00\x00\x18ftypheic").startswith(b"\x89PNG")
    assert calls[0][:3] == ["/usr/bin/sips", "-s", "format"]


def test_the_private_folder_is_removed_even_when_sips_fails(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    seen = []
    real = heic.tempfile.mkdtemp

    def mkdtemp(*a, **k):
        seen.append(real(*a, **k))
        return seen[-1]

    monkeypatch.setattr(heic.tempfile, "mkdtemp", mkdtemp)
    fake_run(monkeypatch, writes_png=False)
    with pytest.raises(Exception):  # noqa: B017
        heic_to_png(b"x")
    import os

    assert seen and not os.path.exists(seen[0])


def test_off_macos_heic_is_unavailable(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(EngineUnavailable):
        heic_to_png(b"x")


@pytest.mark.skipif(sys.platform != "darwin", reason="sips is a macOS tool")
def test_sips_converts_a_real_heic(photo, tmp_path):
    jpg, out = tmp_path / "a.jpg", tmp_path / "a.heic"
    jpg.write_bytes(photo)
    made = subprocess.run(
        ["/usr/bin/sips", "-s", "format", "heic", str(jpg), "--out", str(out)],
        capture_output=True,
        check=False,
    )
    if made.returncode != 0 or not out.exists():
        pytest.skip("this Mac cannot write HEIC")
    assert heic_to_png(out.read_bytes()).startswith(b"\x89PNG")
