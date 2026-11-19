"""Oracle recordings, and the written rule that picks the smoke documents.

An oracle recording answers from the ground truth: the page lines are the truth lines, the type
answer is the truth type and the fill answer is the truth fields. Scoring it must give a perfect
result, which checks the scorers and the filing rules without a model. The committed smoke
recordings are oracle ones until a run on the real models replaces them.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from vault_synth.model import SynthDoc
from vault_synth.sets import load_set, lowest_base

from household_vault.reading.lines import Line, PageText
from household_vault.reading.recorded import Recording, write_recording
from household_vault.reading.source import document_key

ORACLE_ENGINE = "oracle"
PAGE_SIZE = (1000, 1400)

HAND_DRAWN_TYPES = (
    "health_policy",
    "vehicle_policy",
    "warranty_card",
    "tax_invoice",
    "aadhaar",
    "pan",
    "card_front",
    "prescription",
    "lab_report",
)
EXTRA_PHOTO_TYPES = ("passport", "life_policy", "utility_bill", "payslip", "card_statement")
SMOKE_RULE = (
    "val documents. The photo of base 1 of each of the nine hand-drawn types and of passport, "
    "life_policy, utility_bill, payslip and card_statement; the first two locked PDFs (by id) "
    "that expect no question; the photo of the first card with a back (two files); the clean "
    "PDFs of the outsider document (prescription) and the missing-field document (pan) that the "
    "generator guarantees in val, and of health_policy; the scans of aadhaar and tax_invoice."
)


def _pages(doc: SynthDoc) -> list[PageText]:
    width, height = PAGE_SIZE
    by_page: dict[int, list[Line]] = {}
    for ln in doc.lines:
        by_page.setdefault(ln.page, []).append(ln)
    return [
        PageText(page=n, width=width, height=height, lines=lines)
        for n, lines in sorted(by_page.items())
    ]


def oracle_recording(doc: SynthDoc, files: Sequence[bytes]) -> Recording:
    return Recording(
        key=document_key(files),
        doc_id=doc.doc_id,
        pages=_pages(doc),
        classify_raw=json.dumps({"doc_type": doc.doc_type.value}),
        fill_raw=json.dumps(doc.fields),
        seconds={"read": 0.0, "classify": 0.0, "fill": 0.0},
        engine=ORACLE_ENGINE,
        prompt_version="v2",
    )


def smoke_selection(docs: Sequence[SynthDoc]) -> list[str]:
    """The ids of the smoke documents, by the written rule in SMOKE_RULE."""
    val = {d.doc_id: d for d in docs if d.split == "val"}
    base = lowest_base("val", 10_000)
    assert base is not None
    chosen: list[str] = []
    for t in (*HAND_DRAWN_TYPES, *EXTRA_PHOTO_TYPES):
        chosen.append(f"{t}-{base}-photo")
    locked = sorted(d.doc_id for d in val.values() if d.variant == "locked" and not d.expected_ask)
    chosen += locked[:2]
    back = sorted(d.doc_id for d in val.values() if d.variant == "photo" and len(d.files) > 1)
    chosen.append(back[0])
    chosen += [f"prescription-{base}-clean", f"pan-{base}-clean", f"health_policy-{base}-clean"]
    chosen += [f"aadhaar-{base}-scan", f"tax_invoice-{base}-scan"]
    missing = [i for i in chosen if i not in val]
    if missing:
        raise ValueError(f"not in the val split: {missing}")
    return chosen


def load_smoke(set_dir: Path) -> list[str]:
    """The document ids in the set's smoke.json."""
    data = json.loads((set_dir / "smoke.json").read_text(encoding="utf-8"))
    return [str(i) for i in data["documents"]]


def smoke_json(set_dir: Path) -> str:
    docs = load_set(set_dir)
    body = {
        "set": set_dir.name,
        "split": "val",
        "rule": SMOKE_RULE,
        "documents": smoke_selection(docs),
    }
    return json.dumps(body, indent=2) + "\n"


def write_oracle_recordings(set_dir: Path, ids: Sequence[str], folder: Path) -> None:
    """One oracle recording per document id, in folder."""
    by_id = {d.doc_id: d for d in load_set(set_dir)}
    for doc_id in ids:
        doc = by_id[doc_id]
        files = [(set_dir / name).read_bytes() for name in doc.files]
        write_recording(folder, oracle_recording(doc, files))
