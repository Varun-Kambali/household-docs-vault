"""Run metadata that every results file records: date, machine, OS, Python, commit, dirty flag."""

from __future__ import annotations

import datetime
import platform
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass

DEFAULT_DIRTY_PATHS = ("src", "synth", "evals", "spikes", "finetune")
# results files and recordings are outputs of a run, so writing them must not mark the code dirty
EXCLUDES = (":(exclude,glob)**/results/**", ":(exclude)evals/recordings")


@dataclass(frozen=True)
class RunMeta:
    date: str
    machine: str
    os: str
    python: str
    commit: str
    code_dirty: bool


def _out(*cmd: str) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip()


def machine_name() -> str:
    """On a Mac the chip and memory ("Apple M5, 16 GB"); elsewhere the architecture and OS."""
    if platform.system() == "Darwin":
        try:
            brand = _out("sysctl", "-n", "machdep.cpu.brand_string")
            gib = round(int(_out("sysctl", "-n", "hw.memsize")) / 2**30)
            return f"{brand}, {gib} GB"
        except (subprocess.SubprocessError, OSError, ValueError):
            pass
    return f"{platform.machine()}, {platform.system()}"


def _os_name() -> str:
    if platform.system() == "Darwin":
        return f"macOS {platform.mac_ver()[0]}"
    return f"{platform.system()} {platform.release()}"


def run_meta(dirty_paths: Sequence[str] = DEFAULT_DIRTY_PATHS) -> RunMeta:
    machine = machine_name()
    commit = _out("git", "rev-parse", "--short", "HEAD")
    status = _out("git", "status", "--porcelain", "--", *dirty_paths, *EXCLUDES)
    return RunMeta(
        date=datetime.date.today().isoformat(),
        machine=machine,
        os=_os_name(),
        python=sys.version.split()[0],
        commit=commit,
        code_dirty=bool(status),
    )
