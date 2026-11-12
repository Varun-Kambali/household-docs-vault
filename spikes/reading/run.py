"""Run the reading spike: one subprocess per engine, one results file per engine.

uv run python -m spikes.reading.run --set evals/datasets/spike-v0 [--engine NAME ...]
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from vault_synth.model import SynthDoc

from spikes.reading.engines import ENGINES, EngineUnavailable
from spikes.reading.score import PageScore, score_page

DPI = 200
MACHINE = "Apple M5, 16 GB"
RESULTS = Path(__file__).parent / "results"


def _render_pdf(pdf: Path, out: Path) -> Path:
    import pypdfium2 as pdfium

    page = pdfium.PdfDocument(str(pdf))[0]
    page.render(scale=DPI / 72).to_pil().convert("RGB").save(out)
    return out


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def summarise(docs: list[dict]) -> dict:
    out = {}
    for variant in ("clean", "photo"):
        rows = [d for d in docs if d["variant"] == variant]
        out[variant] = {
            "median_cer": _median([d["cer"] for d in rows]),
            "median_line_recall": _median([d["line_recall"] for d in rows]),
            "mean_line_recall": statistics.fmean(d["line_recall"] for d in rows) if rows else None,
            "median_seconds_per_page": _median([d["seconds"] for d in rows]),
            "documents": len(rows),
        }
    return out


def worker(engine_name: str, dataset: Path) -> dict:
    """Runs inside the per-engine subprocess; returns the engine's result body."""
    try:
        engine = ENGINES[engine_name]()
    except EngineUnavailable as exc:
        return {"status": "unavailable", "reason": str(exc)}
    except Exception as exc:  # a model that fails to load is recorded, not fatal
        return {"status": "unavailable", "reason": f"failed to load: {exc}"}
    docs = sorted(dataset.glob("*-clean.json")) + sorted(dataset.glob("*-photo.json"))
    records = [SynthDoc.model_validate_json(p.read_text()) for p in docs]
    results: list[dict] = []
    with tempfile.TemporaryDirectory() as tmp:
        inputs = []
        for rec in records:
            src = dataset / rec.files[0]
            image = (
                _render_pdf(src, Path(tmp) / f"{rec.doc_id}.png") if src.suffix == ".pdf" else src
            )
            inputs.append((rec, image))
        engine.read(inputs[0][1])  # warm-up page, not timed or scored
        for rec, image in inputs:
            start = time.perf_counter()
            got = engine.read(image)
            seconds = time.perf_counter() - start
            truth = [line for line in rec.lines if line.page == 0]
            s: PageScore = score_page(truth, got)
            results.append(
                {
                    "doc_id": rec.doc_id,
                    "doc_type": rec.doc_type,
                    "variant": rec.variant,
                    "cer": s.cer,
                    "line_recall": s.line_recall,
                    "matched": s.matched,
                    "truth_lines": s.truth_lines,
                    "seconds": seconds,
                }
            )
    return {
        "status": "ok",
        "engine_version": getattr(engine, "version", "unknown"),
        "documents": results,
        "summary": summarise(results),
    }


def run_engine(engine_name: str, dataset: Path) -> dict:
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        out_path = Path(f.name)
    cmd = [
        sys.executable, "-m", "spikes.reading.run",
        "--worker", engine_name, "--set", str(dataset), "--out", str(out_path),
    ]  # fmt: skip
    proc = subprocess.Popen(cmd)
    _, status, usage = os.wait4(proc.pid, 0)
    proc.returncode = os.waitstatus_to_exitcode(status)
    if proc.returncode != 0:
        out_path.unlink(missing_ok=True)
        return {"status": "failed", "reason": f"worker exited with {proc.returncode}"}
    body = json.loads(out_path.read_text())
    out_path.unlink()
    if body["status"] == "ok":
        body["peak_rss_mb"] = round(usage.ru_maxrss / 1024 / 1024, 1)  # bytes on macOS
    return body


def _commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", type=Path, required=True)
    ap.add_argument("--engine", action="append", choices=list(ENGINES))
    ap.add_argument("--worker", choices=list(ENGINES))
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    if args.worker:
        args.out.write_text(json.dumps(worker(args.worker, args.set)))
        return
    commit = _commit()
    today = datetime.date.today().isoformat()
    RESULTS.mkdir(exist_ok=True)
    for name in args.engine or list(ENGINES):
        body = run_engine(name, args.set)
        record = {
            "date": today,
            "engine": name,
            "commit": commit,
            "dataset": args.set.name,
            "machine": MACHINE,
            "dpi_clean": DPI,
            **body,
        }
        path = RESULTS / f"{today}_{name}_{commit}.json"
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
        print(f"{name}: {body['status']} -> {path}")
        if body["status"] == "ok":
            print(json.dumps({**body["summary"], "peak_rss_mb": body["peak_rss_mb"]}, indent=2))


if __name__ == "__main__":
    main()
