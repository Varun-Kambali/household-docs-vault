"""Turn the synthetic documents into chat-format training examples.

    uv run python -m finetune.prepare --set evals/datasets/spike-v0 --out finetune/data

The prompt is the extraction spike's prompt, imported, so a model trained here sees at training
time exactly what it sees at inference time. A document's clean and photo variants share a
`base_id` and always land in the same split, so the held-out set never contains a page whose twin
was trained on.

Needs only the default dependencies; torch and friends are in the `finetune` group.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from vault_synth.model import SynthDoc

from household_vault.reading.prompt import PROMPT_V1, schema_json, user_prompt
from household_vault.safety import assert_safe_path
from household_vault.schemas import SCHEMAS

SYSTEM = PROMPT_V1.system

DEFAULT_SPLIT = {"train": 0.7, "val": 0.15, "test": 0.15}


def to_example(doc: SynthDoc, schema: type[BaseModel], ocr_text: str | None) -> dict[str, Any]:
    """One chat example. The user turn names the page image when ocr_text is None.

    "images" lists the page files relative to the dataset folder (empty for text examples), and
    the trainer attaches them to the user turn. The answer is the ground-truth fields as JSON.
    """
    return {
        "doc_id": doc.doc_id,
        "base_id": doc.base_id,
        "doc_type": doc.doc_type.value,
        "variant": doc.variant,
        "images": list(doc.files) if ocr_text is None else [],
        "messages": [
            {"role": "system", "content": SYSTEM},
            {
                "role": "user",
                "content": user_prompt(doc.doc_type.value, schema_json(schema), ocr_text),
            },
            {"role": "assistant", "content": json.dumps(doc.fields, ensure_ascii=False)},
        ],
    }


def _load(set_dir: Path) -> list[SynthDoc]:
    paths = sorted(set_dir.glob("*-clean.json")) + sorted(set_dir.glob("*-photo.json"))
    return [SynthDoc.model_validate_json(p.read_text()) for p in paths]


def _cut(n: int, split: dict[str, float]) -> dict[str, int]:
    """How many base documents go to each split: rounded, at least one each, remainder to train."""
    names = list(split)
    sizes = {k: max(1, round(n * split[k])) for k in names}
    sizes[names[0]] = n - sum(v for k, v in sizes.items() if k != names[0])
    if sizes[names[0]] < 1:
        raise ValueError(f"{n} documents are too few for {len(names)} splits")
    return sizes


def prepare(
    set_dir: Path,
    out: Path,
    split: dict[str, float],
    seed: int,
    ocr: dict[str, str] | None = None,
) -> dict[str, int]:
    """Write one JSONL per split into out and return the example count per split.

    ocr maps doc_id to the page's text; when given, examples carry text instead of an image.
    """
    if abs(sum(split.values()) - 1.0) > 1e-9:
        raise ValueError(f"split fractions must sum to 1, got {sum(split.values())}")
    out = assert_safe_path(out)
    docs = _load(set_dir)
    by_base: dict[str, list[SynthDoc]] = defaultdict(list)
    for d in docs:
        by_base[d.base_id].append(d)
    bases = sorted(by_base)
    random.Random(seed).shuffle(bases)
    sizes = _cut(len(bases), split)
    out.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    start = 0
    for name, size in sizes.items():
        rows = [
            to_example(d, SCHEMAS[d.doc_type], None if ocr is None else ocr[d.doc_id])
            for base in bases[start : start + size]
            for d in by_base[base]
        ]
        start += size
        assert_safe_path(out / f"{name}.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
        )
        counts[name] = len(rows)
    return counts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", type=Path, default=Path("evals/datasets/spike-v0"))
    ap.add_argument("--out", type=Path, default=Path("finetune/data"))
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    args.set = assert_safe_path(args.set)
    print(json.dumps(prepare(args.set, args.out, DEFAULT_SPLIT, args.seed)))


if __name__ == "__main__":
    main()
