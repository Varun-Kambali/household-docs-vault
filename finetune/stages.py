"""Stage records for the fine-tune path spike.

Each stage (prepare, train, merge, convert, import, load, extract) leaves a small JSON file in
`finetune/out/stages/`. `collect` joins them into the committed results file. A command stage
runs through `run`, which times it and samples the peak memory of the process and its children:

    uv run python -m finetune.stages run convert -- <command> <args>
    uv run python -m finetune.stages collect --run mac-mps
"""

from __future__ import annotations

import argparse
import datetime
import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from household_vault.safety import assert_safe_path

OUT = Path("finetune/out")
RESULTS = Path(__file__).parent / "results"
MACHINE = "Apple M5, 16 GB"
SAMPLE_EVERY_S = 0.25
STAGES = ["prepare", "train", "merge", "convert", "import", "load", "extract"]


def stage_path(name: str) -> Path:
    return assert_safe_path(OUT / "stages" / f"{name}.json")


def write_stage(name: str, record: dict[str, Any]) -> None:
    path = stage_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"stage": name, **record}, indent=2, ensure_ascii=False) + "\n")


class PeakRss:
    """Highest resident memory of a process tree, in MiB, sampled in a thread."""

    def __init__(self, pid: int | None = None) -> None:
        import psutil

        self.proc = psutil.Process(pid)
        self.peak_mib = 0.0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def sample(self) -> None:
        import psutil

        total = 0
        try:
            for p in [self.proc, *self.proc.children(recursive=True)]:
                try:
                    total += p.memory_info().rss
                except psutil.NoSuchProcess:
                    continue
        except psutil.NoSuchProcess:
            return
        self.peak_mib = max(self.peak_mib, total / 1024 / 1024)

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.sample()
            self._stop.wait(SAMPLE_EVERY_S)

    def __enter__(self) -> PeakRss:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join()
        self.sample()


def run_command(name: str, cmd: list[str]) -> int:
    start = time.perf_counter()
    with PeakRss() as peak:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    seconds = time.perf_counter() - start
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    ok = proc.returncode == 0
    write_stage(
        name,
        {
            "status": "ok" if ok else "failed",
            "command": " ".join(cmd),
            "error": None if ok else (proc.stderr or proc.stdout).strip()[-1500:],
            "seconds": round(seconds, 1),
            "peak_rss_mib": round(peak.peak_mib, 1),
            "memory_note": "peak resident memory of this command and its child processes, "
            "psutil every 0.25 s",
        },
    )
    return proc.returncode


def _commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()


def _order(p: Path) -> tuple[int, str]:
    base = p.stem.split("-")[0]
    return (STAGES.index(base) if base in STAGES else len(STAGES), p.stem)


def collect(run: str, settings: dict[str, Any]) -> Path:
    stages = {}
    for p in sorted(assert_safe_path(OUT / "stages").glob("*.json"), key=_order):
        stages[p.stem] = json.loads(p.read_text())
    today = datetime.date.today().isoformat()
    commit = _commit()
    record = {
        "date": today,
        "commit": commit,
        "run": run,
        "machine": MACHINE,
        "settings": settings,
        "stages": stages,
    }
    RESULTS.mkdir(exist_ok=True)
    path = assert_safe_path(RESULTS / f"{today}_{run}_{commit}.json")
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    return path


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("name", choices=STAGES)
    r.add_argument("command", nargs=argparse.REMAINDER)
    c = sub.add_parser("collect")
    c.add_argument("--run", required=True)
    c.add_argument("--settings", type=Path, required=True, help="JSON file of run settings")
    args = ap.parse_args()
    if args.cmd == "run":
        cmd = args.command[1:] if args.command[:1] == ["--"] else args.command
        raise SystemExit(run_command(args.name, cmd))
    print(collect(args.run, json.loads(args.settings.read_text())))


if __name__ == "__main__":
    main()
