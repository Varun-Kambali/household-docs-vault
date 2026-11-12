"""Run the extraction spike: one candidate at a time over the 36 spike documents.

ollama serve &    # plain process; stop it when done
uv run --group spikes python -m spikes.extraction.run --set evals/datasets/spike-v0
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import statistics
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from vault_synth.model import SynthDoc

from household_vault.safety import assert_safe_path
from household_vault.schemas import SCHEMAS
from spikes.extraction.candidates import (
    CANDIDATES,
    Candidate,
    CandidateUnavailable,
    OllamaCandidate,
)
from spikes.extraction.prompt import PROMPT_VERSION, ocr_to_text, schema_json
from spikes.extraction.score import DocScore, score_doc

DPI = 200
MACHINE = "Apple M5, 16 GB"
DATASET = "spike-v0"
RESULTS = Path(__file__).parent / "results"
SAMPLE_EVERY_S = 0.25


@dataclass
class CandidateResult:
    status: Literal["ok", "did_not_fit", "unavailable"]
    scores: list[DocScore] = field(default_factory=list)
    seconds: list[float] = field(default_factory=list)
    peak_rss_mb: float | None = None
    reason: str | None = None
    errors: list[str | None] = field(default_factory=list)
    raw: list[str] = field(default_factory=list)
    loaded_size_mb: float | None = None
    baseline_rss_mb: float | None = None


@dataclass
class Prepared:
    files: list[Path]
    ocr_text: str | None
    ocr_seconds: float


def _render_pdf(pdf: Path, out: Path) -> Path:
    import pypdfium2 as pdfium

    page = pdfium.PdfDocument(str(pdf))[0]
    page.render(scale=DPI / 72).to_pil().convert("RGB").save(out)
    return out


def prepare(docs: list[SynthDoc], dataset: Path, tmp: Path, with_ocr: bool) -> dict[str, Prepared]:
    """Page images (PDF rendered at 200 dpi, photos as they are) and, if asked, OCR text."""
    engine = None
    if with_ocr:
        from spikes.reading.engines import AppleVision

        engine = AppleVision()
    out: dict[str, Prepared] = {}
    for rec in docs:
        src = dataset / rec.files[0]
        image = _render_pdf(src, tmp / f"{rec.doc_id}.png") if src.suffix == ".pdf" else src
        text, secs = None, 0.0
        if engine is not None:
            engine.read(image) if not out else None  # one untimed warm-up read
            start = time.perf_counter()
            text = ocr_to_text(engine.read(image))
            secs = time.perf_counter() - start
        out[rec.doc_id] = Prepared([image], text, secs)
    return out


class _RssSampler:
    """Samples a candidate's resident memory in a thread and keeps the peak."""

    def __init__(self, c: Candidate) -> None:
        self.c = c
        self.peak: float | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                v = self.c.rss_mb()
            except Exception:  # a process vanishing between listing and reading
                v = None
            if v is not None and (self.peak is None or v > self.peak):
                self.peak = v
            self._stop.wait(SAMPLE_EVERY_S)

    def __enter__(self) -> _RssSampler:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join()


def run_candidate(
    c: Candidate,
    docs: list[SynthDoc],
    dataset: Path | None = None,
    prepared: dict[str, Prepared] | None = None,
) -> CandidateResult:
    result = CandidateResult(status="ok")
    try:
        result.baseline_rss_mb = c.rss_mb()
    except Exception:
        result.baseline_rss_mb = None
    sampler = _RssSampler(c)
    with sampler:
        try:
            c.load()
        except CandidateUnavailable as exc:
            return CandidateResult(status="unavailable", reason=str(exc))
        except Exception as exc:  # MemoryError, an Ollama out-of-memory error, a refused load
            c.unload()
            return CandidateResult(
                status="did_not_fit",
                reason=f"{type(exc).__name__}: {exc}",
                peak_rss_mb=sampler.peak,
            )
        try:
            with tempfile.TemporaryDirectory() as tmp_name:
                if prepared is None and docs:
                    assert dataset is not None
                    prepared = prepare(
                        docs, dataset, assert_safe_path(Path(tmp_name)), c.kind == "text"
                    )
                for rec in docs:
                    p = (prepared or {})[rec.doc_id]
                    schema = SCHEMAS[rec.doc_type]
                    if isinstance(c, OllamaCandidate):
                        c.doc_type = rec.doc_type.value
                    start = time.perf_counter()
                    error = None
                    try:
                        got = c.extract(p.files, p.ocr_text, schema_json(schema))
                    except Exception as exc:  # one bad document is a zero, not a crash
                        got, error = "", f"{type(exc).__name__}: {exc}"
                    elapsed = (
                        time.perf_counter() - start + (p.ocr_seconds if c.kind == "text" else 0)
                    )
                    result.scores.append(score_doc(rec.fields, got, schema))
                    result.seconds.append(elapsed)
                    result.errors.append(error)
                    result.raw.append(got)
            result.loaded_size_mb = c.loaded_size_mb()
        finally:
            c.unload()
    result.peak_rss_mb = sampler.peak
    return result


def _rate(rows: list[tuple[SynthDoc, DocScore]]) -> dict:
    fields = [v for _, s in rows for v in s.exact.values()]
    return {
        "documents": len(rows),
        "fields": len(fields),
        "field_exact": sum(fields) / len(fields) if fields else None,
        "json_valid": sum(s.valid_json for _, s in rows) / len(rows) if rows else None,
    }


def summarise(docs: list[SynthDoc], res: CandidateResult) -> dict:
    out: dict = {}
    for variant in ("clean", "photo"):
        idx = [i for i, d in enumerate(docs) if d.variant == variant]
        rows = [(docs[i], res.scores[i]) for i in idx]
        secs = [res.seconds[i] for i in idx]
        entry = _rate(rows)
        entry["median_seconds"] = statistics.median(secs) if secs else None
        entry["mean_seconds"] = statistics.fmean(secs) if secs else None
        entry["max_seconds"] = max(secs) if secs else None
        by_type: dict = {}
        by_field: dict = {}
        for t in sorted({d.doc_type.value for d, _ in rows}):
            sub = [(d, s) for d, s in rows if d.doc_type.value == t]
            by_type[t] = _rate(sub)
            keys = sorted({k for _, s in sub for k in s.exact})
            by_field[t] = {
                k: sum(s.exact[k] for _, s in sub if k in s.exact)
                / sum(1 for _, s in sub if k in s.exact)
                for k in keys
            }
        entry["by_type"] = by_type
        entry["by_field"] = by_field
        out[variant] = entry
    return out


def _commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()


def _file_safe(tag: str) -> str:
    return re.sub(r"[^A-Za-z0-9.-]+", "-", tag)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", type=Path, required=True)
    ap.add_argument("--model", action="append", choices=list(CANDIDATES))
    ap.add_argument("--limit", type=int, help="first N documents only, for a smoke run")
    args = ap.parse_args()
    dataset = args.set
    paths = sorted(dataset.glob("*-clean.json")) + sorted(dataset.glob("*-photo.json"))
    docs = [SynthDoc.model_validate_json(p.read_text()) for p in paths]
    if args.limit:
        docs = docs[: args.limit]
    commit = _commit()
    today = datetime.date.today().isoformat()
    results_dir = assert_safe_path(RESULTS)
    results_dir.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = assert_safe_path(Path(tmp_name))
        prepared = prepare(docs, dataset, tmp, with_ocr=True)  # OCR once, shared by text models
        for model in args.model or list(CANDIDATES):
            _, kind = CANDIDATES[model]
            c = OllamaCandidate(model, kind)  # type: ignore[arg-type]
            res = run_candidate(c, docs, dataset, prepared)
            record = {
                "date": today,
                "model": model,
                "digest": c.digest,
                "runtime": c.runtime,
                "runtime_version": c.runtime_version,
                "commit": commit,
                "dataset": dataset.name,
                "machine": MACHINE,
                "prompt_version": PROMPT_VERSION,
                "kind": kind,
                "dpi_clean": DPI,
                "status": res.status,
                "reason": res.reason,
                "peak_rss_mb": round(res.peak_rss_mb, 1) if res.peak_rss_mb else None,
                "baseline_rss_mb": round(res.baseline_rss_mb, 1) if res.baseline_rss_mb else None,
                "loaded_size_mb": round(res.loaded_size_mb, 1) if res.loaded_size_mb else None,
                "max_prompt_tokens": c.max_prompt_tokens,
                "num_ctx": 12288,
                "summary": summarise(docs, res) if res.status == "ok" else None,
                "documents": [
                    {
                        "doc_id": d.doc_id,
                        "doc_type": d.doc_type.value,
                        "variant": d.variant,
                        "valid_json": s.valid_json,
                        "exact": s.exact,
                        "seconds": round(sec, 2),
                        "error": err,
                        "output": raw,
                    }
                    for d, s, sec, err, raw in zip(
                        docs, res.scores, res.seconds, res.errors, res.raw, strict=False
                    )
                ],
            }
            path = results_dir / f"{today}_{_file_safe(model)}_{commit}.json"
            assert_safe_path(path).write_text(
                json.dumps(record, indent=2, ensure_ascii=False) + "\n"
            )
            print(f"{model}: {res.status} -> {path}")
            if res.status == "ok":
                print(
                    json.dumps(
                        {**record["summary"]["photo"], "peak_rss_mb": record["peak_rss_mb"]},
                        default=str,
                    )[:600]
                )


if __name__ == "__main__":
    main()
