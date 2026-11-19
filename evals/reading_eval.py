"""The reading eval: the real reader and the filing rules on every document of a split.

Each document is read as the app reads it (`read_document` in dev mode), then `decide` says where
it would go. Nothing is filed here; `evals.filing_eval` replays the same readings through the
real worker. Metric definitions are in `evals/README.md`.
"""

from __future__ import annotations

import hashlib
import json
import statistics
from collections import defaultdict
from collections.abc import Collection, Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, JsonValue
from vault_synth.data import REFERENCE_DATE
from vault_synth.model import SynthDoc
from vault_synth.sets import load_set, locked_password

from household_vault.filing.decide import Decision, decide
from household_vault.intake.sniff import FileKind, sniff
from household_vault.people import Household, load_household
from household_vault.reading.engines import Engines, PageReader
from household_vault.reading.lines import PageText
from household_vault.reading.pipeline import Reading, read_document
from household_vault.reading.recorded import (
    Recording,
    recorded_engines,
    recorded_seconds,
    write_recording,
)
from household_vault.reading.render import DamagedFileError, LockedPdfError
from household_vault.reading.source import DocumentSource, document_key
from household_vault.reasons import Reason
from household_vault.results import run_meta
from household_vault.schemas import SCHEMAS
from household_vault.schemas.parse import parse_fields
from household_vault.scoring import score_fields, score_page

PERSON_ASKS = frozenset({Reason.person_unknown, Reason.person_unsure})


class DocResult(BaseModel):
    """One document's scores. Booleans, counts and numbers only: never a field value."""

    doc_id: str
    base_id: str
    doc_type: str
    variant: str
    expected_ask: list[str]
    got_type: str | None
    type_ok: bool
    owner_ok: bool | None
    linked_ok: bool
    exact: dict[str, bool]
    # per field, [tp, fp, fn]; they sum to tp, fp and fn below
    field_counts: dict[str, list[int]]
    tp: int
    fp: int
    fn: int
    line_recall: list[float]
    seconds: float
    outcome: Literal["file", "ask"]
    reasons: list[str]
    silent_misfile: bool


# -- the rules ------------------------------------------------------------------------------------


def person_ok(truth: SynthDoc, decision: Decision) -> bool | None:
    """Whose document it is: None for a home document (no person to get right). Where the page
    names an outsider or an unclear name, the app is right only when it asked about the person."""
    if truth.owner == "home":
        return None
    if truth.owner is None:
        return decision.outcome == "ask" and bool(PERSON_ASKS & set(decision.reasons))
    return decision.owner == truth.owner


def silent_misfile(truth: SynthDoc, decision: Decision) -> bool:
    """The app would file the document, to an owner or folder other than the truth's."""
    return decision.outcome == "file" and (
        decision.owner != truth.owner or decision.folder != truth.folder
    )


def _linked_ok(truth: SynthDoc, decision: Decision) -> bool:
    """Linked people never include the owner (Task 18), in the record and in the people table."""
    want = set(truth.linked_people) - {str(truth.owner)}
    got = set(decision.linked) - {str(decision.owner)}
    return want == got


def field_f1(results: Sequence[DocResult]) -> float:
    tp = sum(r.tp for r in results)
    fp = sum(r.fp for r in results)
    fn = sum(r.fn for r in results)
    denominator = 2 * tp + fp + fn
    return 2 * tp / denominator if denominator else 1.0


def _item_text(item: object) -> str:
    key = getattr(item, "key", None)
    return str(key()) if callable(key) else str(item)


def _scoring_truth(doc: SynthDoc) -> dict[str, Any]:
    """The truth fields as `score_fields` compares them: a list of structured items becomes the
    list of their item keys."""
    schema = SCHEMAS[doc.doc_type]
    typed = parse_fields(schema, doc.fields, mode="dev").model
    out: dict[str, Any] = {}
    for name, value in doc.fields.items():
        if isinstance(value, list) and name in schema.model_fields:
            items = getattr(typed, name)
            out[name] = [_item_text(i) for i in items] if items is not None else value
        else:
            out[name] = value
    return out


def _field_counts(
    schema: type[BaseModel],
    truth: Mapping[str, Any],
    exact: Mapping[str, bool],
    got: BaseModel,
) -> dict[str, list[int]]:
    """[tp, fp, fn] for each field that took part, split the way `score_fields` totals them: a
    value where the page prints none is a false positive; a printed field is a true positive when
    right, else a false negative, and also a false positive when something wrong was read."""
    counts: dict[str, list[int]] = {}
    for name in schema.model_fields:
        value = getattr(got, name, None)
        if truth.get(name) is None:
            if value is not None:
                counts[name] = [0, 1, 0]
        elif exact[name]:
            counts[name] = [1, 0, 0]
        else:
            counts[name] = [0, int(value is not None), 1]
    return counts


def score_reading(
    doc: SynthDoc,
    reading: Reading,
    decision: Decision,
    pages: Sequence[PageText],
    seconds: float,
) -> DocResult:
    """Score one reading and its decision against the truth. A reading of the wrong type scores
    every truth field as wrong and counts no false positives: its fields answer another schema."""
    got_type = reading.doc_type
    schema = SCHEMAS[doc.doc_type]
    truth = _scoring_truth(doc)
    if got_type is doc.doc_type:
        raw: dict[str, JsonValue] = {**reading.fields, **reading.secret_values}
        got = parse_fields(schema, raw, mode="dev").model
        fields = score_fields(schema, truth, got)
        exact, tp, fp, fn = fields.exact, fields.tp, fields.fp, fields.fn
        counts = _field_counts(schema, truth, fields.exact, got)
    else:
        exact = {k: False for k, v in truth.items() if v is not None}
        tp, fp, fn = 0, 0, len(exact)
        counts = {name: [0, 0, 1] for name in exact}
    recalls: list[float] = []
    if doc.variant == "photo":
        for number in sorted({ln.page for ln in doc.lines}):
            english = [ln for ln in doc.lines if ln.page == number and ln.lang == "en"]
            got_lines = pages[number].lines if number < len(pages) else []
            recalls.append(score_page(english, got_lines).line_recall)
    return DocResult(
        doc_id=doc.doc_id,
        base_id=doc.base_id,
        doc_type=doc.doc_type.value,
        variant=doc.variant,
        expected_ask=list(doc.expected_ask),
        got_type=got_type.value if got_type else None,
        type_ok=got_type is doc.doc_type,
        owner_ok=person_ok(doc, decision),
        linked_ok=_linked_ok(doc, decision),
        exact=exact,
        field_counts=counts,
        tp=tp,
        fp=fp,
        fn=fn,
        line_recall=recalls,
        seconds=seconds,
        outcome=decision.outcome,
        reasons=[r.value for r in decision.reasons],
        silent_misfile=silent_misfile(doc, decision),
    )


# -- running --------------------------------------------------------------------------------------


class _Capture:
    """Wraps a page reader and keeps what it returned, so the recording holds the pages as read
    (the reading's own pages have card numbers masked)."""

    def __init__(self, inner: PageReader) -> None:
        self.inner = inner
        self.pages: list[PageText] = []

    def read_pages(
        self, source: DocumentSource, sha256: str, password: str | None
    ) -> list[PageText]:
        self.pages = self.inner.read_pages(source, sha256, password)
        return self.pages


def source_of(files: Sequence[bytes]) -> DocumentSource:
    """What the reader is given for a document's files: one file as it is, several photos of
    one card as one upload."""
    kind = sniff(files[0][:64])
    if kind is None or kind is FileKind.audio:
        raise ValueError("the eval set holds only PDFs and photos")
    if len(files) == 1:
        return DocumentSource(kind, data=files[0])
    return DocumentSource(kind, images=list(files))


def _undecided(doc: SynthDoc, reason: Reason) -> DocResult:
    """A document the reader could not open (the app asks for a password or says it is damaged)."""
    return DocResult(
        doc_id=doc.doc_id,
        base_id=doc.base_id,
        doc_type=doc.doc_type.value,
        variant=doc.variant,
        expected_ask=list(doc.expected_ask),
        got_type=None,
        type_ok=False,
        owner_ok=None if doc.owner == "home" else False,
        linked_ok=False,
        exact={k: False for k, v in doc.fields.items() if v is not None},
        field_counts={k: [0, 0, 1] for k, v in doc.fields.items() if v is not None},
        tp=0,
        fp=0,
        fn=sum(v is not None for v in doc.fields.values()),
        line_recall=[],
        seconds=0.0,
        outcome="ask",
        reasons=[reason.value],
        silent_misfile=False,
    )


def load_documents(
    set_dir: Path, split: str, only: Collection[str] | None = None, limit: int | None = None
) -> list[SynthDoc]:
    docs = [d for d in load_set(set_dir) if d.split == split and (only is None or d.doc_id in only)]
    return docs if limit is None else docs[:limit]


def read_and_decide(
    doc: SynthDoc,
    files: Sequence[bytes],
    engines: Engines,
    household: Household,
) -> tuple[Reading, Decision, list[PageText]]:
    """Read one document as the app reads it and decide where it would go. A locked document is
    opened with its derived password. Raises `LockedPdfError` or `DamagedFileError` when the
    reader cannot open it."""
    capture = _Capture(engines.pages)
    password = locked_password(doc.base_id) if doc.variant == "locked" else None
    reading = read_document(
        source_of(files),
        document_key(files),
        Engines(capture, engines.models),
        mode="dev",
        password=password,
    )
    return reading, decide(reading, household, REFERENCE_DATE, []), capture.pages


def run_reading(
    set_dir: Path,
    split: str,
    engines: Engines,
    *,
    record_to: Path | None,
    resume: bool,
    limit: int | None,
    only: Collection[str] | None = None,
) -> list[DocResult]:
    """Read and decide every document of the split. With `record_to`, each reading is recorded
    by its document key; with `resume` too, a document already recorded there is replayed from
    its recording instead of being read again."""
    household = load_household(set_dir / "household.json")
    results: list[DocResult] = []
    for doc in load_documents(set_dir, split, only, limit):
        files = [(set_dir / name).read_bytes() for name in doc.files]
        key = document_key(files)
        replay = record_to is not None and resume and (record_to / f"{key}.json").is_file()
        active = recorded_engines(record_to) if replay and record_to else engines
        try:
            reading, decision, pages = read_and_decide(doc, files, active, household)
        except LockedPdfError:
            results.append(_undecided(doc, Reason.locked))
            continue
        except DamagedFileError:
            results.append(_undecided(doc, Reason.damaged))
            continue
        if record_to is not None and not replay:
            write_recording(
                record_to,
                Recording(
                    key=key,
                    doc_id=doc.doc_id,
                    pages=pages,
                    classify_raw=reading.raw.get("classify"),
                    fill_raw=reading.raw.get("fill"),
                    seconds=dict(reading.seconds),
                    engine=reading.engine,
                    prompt_version=reading.prompt_version,
                ),
            )
        seconds = sum((recorded_seconds(active, key) or reading.seconds).values())
        results.append(score_reading(doc, reading, decision, pages, round(seconds, 3)))
    return results


# -- summary --------------------------------------------------------------------------------------


def _share(hits: int, total: int) -> float:
    return hits / total if total else 1.0


def _exact_rate(results: Sequence[DocResult]) -> float:
    flags = [v for r in results for v in r.exact.values()]
    return _share(sum(flags), len(flags))


def summarise_reading(results: Sequence[DocResult]) -> dict[str, Any]:
    by_variant: dict[str, list[DocResult]] = defaultdict(list)
    by_type: dict[str, list[DocResult]] = defaultdict(list)
    for r in results:
        by_variant[r.variant].append(r)
        by_type[r.doc_type].append(r)
    people = [r.owner_ok for r in results if r.owner_ok is not None]
    expected_clean = [r for r in results if not r.expected_ask]
    photos = [r for r in results if r.variant == "photo"]
    recalls = [v for r in photos for v in r.line_recall]
    seconds = [r.seconds for r in photos]
    by_field: dict[str, list[bool]] = defaultdict(list)
    for r in results:
        for name, ok in r.exact.items():
            by_field[f"{r.doc_type}.{name}"].append(ok)
    counts_by_field: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for r in results:
        for name, c in r.field_counts.items():
            total = counts_by_field[f"{r.doc_type}.{name}"]
            for i in range(3):
                total[i] += c[i]
    return {
        "documents": len(results),
        "by_variant": {v: len(rs) for v, rs in sorted(by_variant.items())},
        "type_accuracy": _share(sum(r.type_ok for r in results), len(results)),
        "person_accuracy": _share(sum(people), len(people)),
        "linked_accuracy": _share(sum(r.linked_ok for r in results), len(results)),
        "field_exact": {
            "all": _exact_rate(results),
            **{v: _exact_rate(rs) for v, rs in sorted(by_variant.items())},
        },
        "field_exact_by_type": {t: _exact_rate(rs) for t, rs in sorted(by_type.items())},
        "field_exact_by_field": {
            name: _share(sum(flags), len(flags)) for name, flags in sorted(by_field.items())
        },
        "field_f1": {"all": field_f1(results)},
        "field_f1_by_type": {t: field_f1(rs) for t, rs in sorted(by_type.items())},
        "field_f1_by_field": {
            name: 2 * c[0] / d if (d := 2 * c[0] + c[1] + c[2]) else 1.0
            for name, c in sorted(counts_by_field.items())
        },
        "line_recall_photo": statistics.fmean(recalls) if recalls else None,
        "silent_misfiles": sum(r.silent_misfile for r in results),
        "silent_misfiles_per_100": 100 * sum(r.silent_misfile for r in results) / len(results)
        if results
        else 0.0,
        "needs_a_look_share": {
            "expected_clean": _share(
                sum(r.outcome == "ask" for r in expected_clean), len(expected_clean)
            )
            if expected_clean
            else 0.0,
            "all": _share(sum(r.outcome == "ask" for r in results), len(results))
            if results
            else 0.0,
        },
        "seconds_photo": {
            "median": statistics.median(seconds) if seconds else None,
            "max": max(seconds) if seconds else None,
        },
    }


def dataset_info(set_dir: Path) -> dict[str, str]:
    manifest = (set_dir / "manifest.json").read_bytes()
    return {"name": set_dir.name, "manifest_sha256": hashlib.sha256(manifest).hexdigest()}


def write_results(
    folder: Path,
    kind: str,
    split: str,
    summary: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    *,
    extra: Mapping[str, Any] | None = None,
) -> Path:
    """Write `<date>_<kind>_<split>_<commit>.json`: the run, the summary and one row per
    document of booleans and numbers. `extra` adds run facts (dataset, models, thresholds)."""
    meta = run_meta()
    body = {
        "kind": kind,
        "split": split,
        "run": asdict(meta),
        **(extra or {}),
        "summary": summary,
        "rows": list(rows),
    }
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{meta.date}_{kind}_{split}_{meta.commit}.json"
    path.write_text(json.dumps(body, indent=1, sort_keys=False) + "\n", encoding="utf-8")
    return path
