"""Run the transcription spike: one subprocess per candidate, one results file per candidate.

uv run --group spikes python -m spikes.transcription.run --set evals/datasets/visits-v0 \
    [--candidate NAME ...]

Render the audio first with `make visits`. Seconds are the wall time of one transcription of a
whole visit, after the model is loaded and one short clip has been transcribed (not scored).
Peak memory is the highest resident set size of this Python process, sampled every 0.25 s, from
before the model loads to the end of the run; MLX runs in-process, so the weights are in it.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from household_vault.results import run_meta
from household_vault.safety import assert_safe_path
from spikes.transcription.candidates import CANDIDATES, timed_load
from spikes.transcription.score import normalise, score_visit, style_counts

RESULTS = Path(__file__).parent / "results"
SAMPLE_SECONDS = 0.25


class PeakRss:
    """Samples this process's resident set size on a thread; `peak_mb` is the highest seen."""

    def __init__(self) -> None:
        import psutil

        self._proc = psutil.Process()
        self.peak_mb = 0.0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            self.sample()
            self._stop.wait(SAMPLE_SECONDS)

    def sample(self) -> float:
        rss = self._proc.memory_info().rss / 1024 / 1024
        self.peak_mb = max(self.peak_mb, rss)
        return rss

    def __enter__(self) -> PeakRss:
        self.sample()
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join()
        self.sample()


def audio_seconds(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    return float(out)


def summarise(visits: list[dict]) -> dict:
    total_audio = sum(v["audio_seconds"] for v in visits)
    total_seconds = sum(v["seconds"] for v in visits)
    return {
        "mean_wer": statistics.fmean(v["wer"] for v in visits),
        "median_wer": statistics.median(v["wer"] for v in visits),
        "visits_with_every_medicine": sum(
            v["medicines_found"] == v["medicines_total"] for v in visits
        ),
        "visits_with_every_medicine_name": sum(
            v["names_found"] == v["medicines_total"] for v in visits
        ),
        "medicines_found": sum(v["medicines_found"] for v in visits),
        "medicine_names_found": sum(v["names_found"] for v in visits),
        "medicines_total": sum(v["medicines_total"] for v in visits),
        "rtf": total_seconds / total_audio,
        "max_visit_rtf": max(v["rtf"] for v in visits),
        "visits": len(visits),
    }


def worker(name: str, dataset: Path) -> dict:
    """Runs inside the per-candidate subprocess; returns the candidate's result body."""
    candidate = CANDIDATES[name]()
    audio_dir = dataset / "audio"
    truths = [json.loads(p.read_text()) for p in sorted(dataset.glob("visit_*.json"))]
    try:
        with PeakRss() as mem:
            baseline_mb = mem.sample()
            load_seconds = timed_load(candidate)
            loaded_mb = mem.sample()
            candidate.transcribe(audio_dir / "warmup.flac")  # warm-up clip, not timed or scored
            visits: list[dict] = []
            for truth in truths:
                audio = audio_dir / f"{truth['visit_id']}.flac"
                length = audio_seconds(audio)
                start = time.perf_counter()
                got = candidate.transcribe(audio)
                seconds = time.perf_counter() - start
                s = score_visit(truth["transcript"], got, truth["medicines"])
                missing = [
                    m for m in truth["medicines"]
                    if not score_visit("x", got, [m]).medicines_found
                ]  # fmt: skip
                visits.append(
                    {
                        "visit_id": truth["visit_id"],
                        "wer": s.wer,
                        "medicines_found": s.medicines_found,
                        "medicines_total": s.medicines_total,
                        "names_found": s.names_found,
                        "medicines_missed": missing,
                        "seconds": seconds,
                        "audio_seconds": length,
                        "rtf": seconds / length,
                        "style_truth": style_counts(truth["transcript"]),
                        "style_got": style_counts(got),
                        "words_truth": len(normalise(truth["transcript"]).split()),
                        "words_got": len(normalise(got).split()),
                        "transcript": got,
                    }
                )
    except Exception as exc:  # a model that fails to load or run is recorded, not fatal
        return {"status": "failed", "reason": f"{type(exc).__name__}: {exc}"}
    return {
        "status": "ok",
        "model": candidate.repo,
        "revision": candidate.revision(),
        "package": candidate.package,
        "package_version": candidate.package_version(),
        "settings": candidate.settings,
        "load_seconds": load_seconds,
        "baseline_rss_mb": round(baseline_mb, 1),
        "rss_after_load_mb": round(loaded_mb, 1),
        "peak_rss_mb": round(mem.peak_mb, 1),
        "visits": visits,
        "summary": summarise(visits),
    }


def run_candidate(name: str, dataset: Path) -> dict:
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        out_path = assert_safe_path(Path(f.name))
    cmd = [
        sys.executable, "-m", "spikes.transcription.run",
        "--worker", name, "--set", str(dataset), "--out", str(out_path),
    ]  # fmt: skip
    code = subprocess.run(cmd).returncode
    if code != 0:
        out_path.unlink(missing_ok=True)
        return {"status": "failed", "reason": f"worker exited with {code}"}
    body = json.loads(out_path.read_text())
    out_path.unlink()
    return body


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", type=Path, required=True)
    ap.add_argument("--candidate", action="append", choices=list(CANDIDATES))
    ap.add_argument("--label", default="", help="suffix for a repeat run, for example r2")
    ap.add_argument("--worker", choices=list(CANDIDATES))
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    args.set = assert_safe_path(args.set)
    if args.worker:
        assert_safe_path(args.out).write_text(json.dumps(worker(args.worker, args.set)))
        return
    dataset = assert_safe_path(args.set)
    meta = run_meta()
    commit, dirty = meta.commit, meta.code_dirty
    manifest = json.loads((dataset / "manifest.json").read_text())
    today = meta.date
    results_dir = assert_safe_path(RESULTS)
    results_dir.mkdir(exist_ok=True)
    for name in args.candidate or list(CANDIDATES):
        body = run_candidate(name, dataset)
        record = {
            "date": today,
            "candidate": name,
            "commit": commit,
            "code_dirty": dirty,
            "run_label": args.label or "r1",
            "dataset": dataset.name,
            "dataset_os": manifest["os"],
            "machine": meta.machine,
            "os": meta.os,
            "python": meta.python,
            **body,
        }
        suffix = f"_{args.label}" if args.label else ""
        path = results_dir / f"{today}_{name}_{commit}{suffix}.json"
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
        print(f"{name}: {body['status']} -> {path}")
        if body["status"] == "ok":
            print(json.dumps({**body["summary"], "peak_rss_mb": body["peak_rss_mb"]}, indent=2))
        else:
            print(body["reason"])


if __name__ == "__main__":
    main()
