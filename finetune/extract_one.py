"""Load the converted model in Ollama and extract one held-out test document.

    ollama serve &     # plain process; stop it afterwards
    uv run --group spikes python -m finetune.extract_one --model vault-spike-qwen3vl-2b

Writes the `load` and `extract` stage records. The result is for ONE document and says nothing
about accuracy; it only shows that the converted model loads and answers in the schema.
"""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path

from vault_synth.model import SynthDoc

from finetune.stages import PeakRss, write_stage
from household_vault.safety import assert_safe_path
from household_vault.schemas import SCHEMAS
from spikes.extraction.candidates import OllamaCandidate
from spikes.extraction.prompt import schema_json
from spikes.extraction.run import _render_pdf
from spikes.extraction.score import score_doc


def first_test_doc(data: Path, set_dir: Path) -> SynthDoc:
    row = json.loads((data / "test.jsonl").read_text().splitlines()[0])
    return SynthDoc.model_validate_json((set_dir / f"{row['doc_id']}.json").read_text())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--data", type=Path, default=Path("finetune/data"))
    ap.add_argument("--set", type=Path, default=Path("evals/datasets/spike-v0"))
    args = ap.parse_args()
    doc = first_test_doc(args.data, args.set)
    schema = SCHEMAS[doc.doc_type]
    cand = OllamaCandidate(args.model, "vision", doc_type=doc.doc_type.value)
    cand.prefill_empty_think = False  # the fine-tuned model is an Instruct build
    t0 = time.perf_counter()
    with PeakRss() as rss:
        try:
            cand.load()
            load = {"status": "ok", "error": None}
        except Exception as exc:
            load = {"status": "failed", "error": f"{type(exc).__name__}: {str(exc)[:1200]}"}
        load["seconds"] = round(time.perf_counter() - t0, 1)
        ollama_peak = max(cand.rss_mb() or 0.0, 0.0)
        write_stage(
            "load",
            {
                **load,
                "ollama_rss_mib_after_load": round(ollama_peak, 1),
                "memory_note": "resident memory of `ollama serve` and its children right after "
                "loading, psutil",
            },
        )
        if load["status"] != "ok":
            return
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = assert_safe_path(Path(tmp_name))
            src = args.set / doc.files[0]
            image = _render_pdf(src, tmp / "page.png") if src.suffix == ".pdf" else src
            t1 = time.perf_counter()
            try:
                got, err = cand.extract([image], None, schema_json(schema)), None
            except Exception as exc:
                got, err = "", f"{type(exc).__name__}: {str(exc)[:1200]}"
            seconds = time.perf_counter() - t1
        peak_server = cand.rss_mb() or 0.0
        cand.unload()
    score = score_doc(doc.fields, got, schema)
    write_stage(
        "extract",
        {
            "status": "ok" if err is None else "failed",
            "error": err,
            "seconds": round(seconds, 1),
            "documents": 1,
            "doc_id": doc.doc_id,
            "doc_type": doc.doc_type.value,
            "valid_json": score.valid_json,
            "fields_correct": sum(score.exact.values()),
            "fields_total": len(score.exact),
            "field_result": score.exact,
            "output": got,
            "ollama_rss_mib_after_extract": round(peak_server, 1),
            "peak_rss_mib": round(rss.peak_mib, 1),
            "memory_note": "peak_rss_mib is this Python client; ollama_rss_* is the server tree "
            "read once after the call. One document: not an accuracy figure.",
        },
    )


if __name__ == "__main__":
    main()
