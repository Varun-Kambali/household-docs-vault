"""The search eval: the real index, retrieval, answers and sentence on a temporary vault, scored on
the `search-v1` questions of a split.

The vault is the split's eval-v1 documents (photo variant, a card with a back uploaded as the
filing eval does) replayed from their recorded readings through the real worker and filer, plus
the extra documents from oracle recordings. Prompt readings and vectors are recorded the same
way (`RecordedPromptReader`, `RecordedEmbedder`), so a run is repeatable with no model. "Today"
is `EVAL_TODAY`. Metric definitions: `evals/README.md`.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import re
import shutil
import time
import uuid
from collections import Counter
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from unittest import mock

import numpy as np
from pydantic import JsonValue
from vault_synth.model import SynthDoc
from vault_synth.sets import Split, load_set

from evals.filing_eval import MASTER_PASSWORD, MaskedCopyPages, _settings, _unlock_all
from evals.recordings import files_as_filed, oracle_recording
from evals.search_set import (
    EVAL_TODAY,
    EVAL_V1,
    SEARCH_DIR,
    SET_SEED,
    Question,
    _list_questions,
    _where,
    load_questions,
    origin_of,
    search_vault_docs,
)
from household_vault.app_state import AppState, build_app_state
from household_vault.config import load_settings
from household_vault.db import Item, ItemState
from household_vault.doctypes import AREA, DocType
from household_vault.filing import filer
from household_vault.leakscan import scan_outputs, waiting_original_paths
from household_vault.people import load_household, normalise_name
from household_vault.reading.engines import Engines
from household_vault.reading.lines import PageText
from household_vault.reading.ollama import ModelUnavailable
from household_vault.reading.recorded import recorded_engines, write_recording
from household_vault.reading.source import DocumentSource, document_key
from household_vault.schemas import SCHEMAS
from household_vault.schemas._coerce import field_kind, parse_amount, parse_date
from household_vault.scoring import IOU_MIN, iou, normalise
from household_vault.search.answer import Answer, NoAnswer, compose, weak_match
from household_vault.search.query import PROMPT_READ, PromptReader, Query, read_prompt, resolve
from household_vault.search.retrieve import Rows
from household_vault.search.sentence import sentence
from household_vault.search.vectors import QUERY_TASK, Embedder, Vectors
from household_vault.vaultroot import INBOX

ORIGINS = ("eval-v1", "extra")
SMOKE_DIR = Path(__file__).resolve().parent / "recordings" / "search-v1" / "smoke"
N_SMOKE_LISTS = 10
_ALL_STATES: tuple[ItemState, ...] = ("queued", "reading", "filed", "asked", "held")


class SearchEvalError(Exception):
    """The vault could not be built as the run needs it (a recording is missing)."""


# -- recordings -----------------------------------------------------------------------------------


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_bytes(data)
    temp.replace(path)


class RecordingMismatch(SearchEvalError):
    """A recordings folder was made by another model than the run expects."""


MANIFEST = "manifest.json"


def _manifest(folder: Path) -> dict[str, Any]:
    try:
        body = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return body if isinstance(body, dict) else {}


def _stamp(folder: Path, role: str, model: str, digest: str | None, *, write: bool) -> None:
    """Write the model a folder's recordings were made with, or refuse a folder that already
    names another model (or another digest, when both are known)."""
    body = _manifest(folder)
    have = body.get(role)
    if isinstance(have, dict):
        same_digest = digest is None or have.get("digest") in (None, digest)
        if have.get("model") != model:
            raise RecordingMismatch(
                f"{folder} holds {role} recordings made with {have.get('model')}, not {model}"
            )
        if not same_digest:
            raise RecordingMismatch(
                f"{folder} holds {role} recordings made with another build of {model} "
                "(the model was pulled again since)"
            )
        return
    if write:
        body[role] = {"model": model, "digest": digest}
        _write(folder / MANIFEST, (json.dumps(body, indent=1) + "\n").encode())


def _expect(folder: Path, role: str, model: str, digest: str | None) -> None:
    have = _manifest(folder).get(role)
    if not isinstance(have, dict):
        raise RecordingMismatch(f"{folder} has no record of the model that made its {role}")
    _stamp(folder, role, model, digest, write=False)


class RecordedPromptReader:
    """Replays the model's JSON for a prompt, keyed by the SHA-256 of the prompt. With `live` it
    asks the real reader for a prompt with no recording, and with `record_to` it writes what the
    reader answered. A recording made under another reading prompt is as good as missing, so a
    change to the prompt forces a new recording."""

    def __init__(
        self,
        folder: Path,
        record_to: Path | None = None,
        *,
        live: PromptReader | None = None,
        name: str = "recorded-prompt-reader",
        model: str | None = None,
        digest: str | None = None,
        expect: str | None = None,
        expect_digest: str | None = None,
        system: str = PROMPT_READ,
    ) -> None:
        if record_to is not None and live is None:
            raise ValueError("recording needs a live reader")
        self.folder = folder
        self.record_to = record_to
        self.live = live
        self.name = live.name if live is not None else name
        if expect is not None:
            _expect(folder, "prompt_reader", expect, expect_digest)
        if record_to is not None and live is not None:
            _stamp(record_to, "prompt_reader", model or live.name, digest, write=True)
        self.system = _sha(system)

    def _load(self, prompt: str) -> str | None:
        path = self.folder / f"{_sha(prompt)}.json"
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(body, dict) or body.get("system_sha256") != self.system:
            return None
        raw = body.get("raw")
        return raw if isinstance(raw, str) else None

    def read(self, prompt: str) -> str:
        found = self._load(prompt)
        if found is not None:
            return found
        if self.live is None:
            raise ModelUnavailable("no recording of this reading")
        raw = self.live.read(prompt)
        if self.record_to is not None:
            body = {"system_sha256": self.system, "model": self.live.name, "raw": raw}
            _write(self.record_to / f"{_sha(prompt)}.json", (json.dumps(body) + "\n").encode())
        return raw


class RecordedEmbedder:
    """Replays vectors as float16, keyed by the SHA-256 of the text (a query's key also holds the
    task line the model is given, so a changed task is a new key). A vector is returned as it was
    stored, so a live run and its replay agree exactly."""

    def __init__(
        self,
        folder: Path,
        record_to: Path | None = None,
        *,
        live: Embedder | None = None,
        name: str | None = None,
        model: str | None = None,
        digest: str | None = None,
        expect: str | None = None,
        expect_digest: str | None = None,
    ) -> None:
        if record_to is not None and live is None:
            raise ValueError("recording needs a live embedder")
        self.folder = folder
        self.record_to = record_to
        self.live = live
        self.name = (
            live.name if live is not None else (name or expect or load_settings(env={}).embed_model)
        )
        self.missing_queries = 0  # query vectors that were not there (search drops to keywords)
        if expect is not None:
            _expect(folder, "embedder", expect, expect_digest)
        if record_to is not None and live is not None:
            _stamp(record_to, "embedder", model or live.name, digest, write=True)

    def _path(self, key: str) -> Path:
        return self.folder / f"{key}.npy"

    def _get(self, key: str) -> Vectors | None:
        try:
            return np.load(self._path(key)).astype(np.float32)  # type: ignore[no-any-return]
        except (OSError, ValueError, EOFError):
            return None

    def _put(self, key: str, vec: Vectors) -> Vectors:
        stored = np.asarray(vec, dtype=np.float16)
        if self.record_to is not None:
            self.record_to.mkdir(parents=True, exist_ok=True)
            target = self.record_to / f"{key}.npy"
            temp = target.with_name(f".{target.name}.tmp.npy")
            np.save(temp, stored)
            temp.replace(target)
        return stored.astype(np.float32)

    def embed_documents(self, texts: list[str]) -> Vectors:
        keys = [_sha(t) for t in texts]
        got = {k: self._get(k) for k in set(keys)}
        todo = [(k, t) for k, t in dict.fromkeys(zip(keys, texts, strict=True)) if got[k] is None]
        if todo:
            if self.live is None:
                raise ModelUnavailable("no recording of this text")
            fresh = self.live.embed_documents([t for _, t in todo])
            for (k, _), vec in zip(todo, fresh, strict=True):
                got[k] = self._put(k, vec)
        vectors = [v for v in (got[k] for k in keys) if v is not None]
        return np.stack(vectors)

    def embed_query(self, text: str) -> Vectors:
        key = _sha(f"{QUERY_TASK}\n{text}")
        found = self._get(key)
        if found is not None:
            return found
        if self.live is None:
            self.missing_queries += 1
            raise ModelUnavailable("no recording of this query")
        return self._put(key, self.live.embed_query(text))


class _Chained:
    """Page reader and models that try one set of recordings and then another."""

    def __init__(self, first: Engines, second: Engines) -> None:
        self.first, self.second = first, second

    def read_pages(
        self, source: DocumentSource, sha256: str, password: str | None
    ) -> list[PageText]:
        try:
            return self.first.pages.read_pages(source, sha256, password)
        except ModelUnavailable:
            return self.second.pages.read_pages(source, sha256, password)

    @property
    def name(self) -> str:
        return self.first.models.name

    def classify(self, ocr_text: str, sha256: str) -> str:
        try:
            return self.first.models.classify(ocr_text, sha256)
        except ModelUnavailable:
            return self.second.models.classify(ocr_text, sha256)

    def fill(self, doc_type: DocType, images: list[bytes], ocr_text: str, sha256: str) -> str:
        try:
            return self.first.models.fill(doc_type, images, ocr_text, sha256)
        except ModelUnavailable:
            return self.second.models.fill(doc_type, images, ocr_text, sha256)


# -- the vault ------------------------------------------------------------------------------------


@dataclass
class _Entry:
    doc: SynthDoc
    files: list[bytes]
    key: str


def _doc_dir(doc: SynthDoc) -> Path:
    return EVAL_V1 if doc.set_name == "eval-v1" else SEARCH_DIR / "extra" / doc.set_name


def _items(state: AppState) -> list[Item]:
    return state.store.items(_ALL_STATES)


class _Counted:
    """Stands in for `uuid` in the filer: ids that come from a counter (hashed, so they read like
    any id), so two builds of one vault have the same ids and so the same order among documents
    that rank alike."""

    def __init__(self) -> None:
        self._n = itertools.count(1)

    def uuid4(self) -> uuid.UUID:
        digest = hashlib.sha256(f"doc-{next(self._n)}".encode()).digest()
        return uuid.UUID(bytes=digest[:16])


def _build(
    docs: Sequence[SynthDoc], recordings: Path, root: Path, embedder: Embedder
) -> tuple[AppState, dict[str, str], list[_Entry]]:
    """The vault over docs, and the map from each filed truth document id to its database id."""
    with mock.patch.object(filer, "uuid", _Counted()):
        return _build_vault(docs, recordings, root, embedder)


def _build_vault(
    docs: Sequence[SynthDoc], recordings: Path, root: Path, embedder: Embedder
) -> tuple[AppState, dict[str, str], list[_Entry]]:
    entries = [
        _Entry(d, files, document_key(files))
        for d in docs
        for files in [files_as_filed([(_doc_dir(d) / n).read_bytes() for n in d.files])]
    ]
    oracle = root / "oracle-extra"
    for e in entries:
        if e.doc.set_name != "eval-v1":
            write_recording(oracle, oracle_recording(e.doc, e.files))
    reading = recorded_engines(recordings)
    extra = recorded_engines(oracle) if oracle.exists() else reading
    chained = _Chained(reading, extra)
    known = {e.key for e in entries}
    settings = _settings(root, recordings)
    shutil.copy(EVAL_V1 / "household.json", settings.household_path)
    state = build_app_state(
        settings,
        engines=Engines(MaskedCopyPages(chained, known), chained),
        embedder=embedder,
    )
    by_key: dict[str, Any] = {e.key: e for e in entries}  # `_unlock_all` reads only `.doc`
    cards = any(e.doc.doc_type is DocType.card_front for e in entries)
    if cards:
        state.gate.create(MASTER_PASSWORD)
        state.gate.lock()  # single card photos wait in Inbox until the store is opened
    # Photos go in first and the other variants of a base after them, so a clean copy or a scan
    # of a document already filed is held as a possible copy, as it would be for the owner.
    singles = [e for e in entries if len(e.files) == 1]
    photos = [e for e in singles if e.doc.variant == "photo"]
    others = [e for e in singles if e.doc.variant != "photo"]
    for e in photos:
        state.vault.write_atomic(f"{INBOX}/{e.doc.files[0]}", e.files[0])
    state.worker.drain()
    if cards:
        state.gate.unlock(MASTER_PASSWORD)
        state.worker.drain()
        for e in (e for e in entries if len(e.files) > 1):
            state.cards.upload(e.files, MASTER_PASSWORD)
    for e in others:
        state.vault.write_atomic(f"{INBOX}/{e.doc.files[0]}", e.files[0])
    state.worker.drain()
    _unlock_all(state, by_key)
    for _ in range(100):  # an embed job still waiting on a first call is run again
        state.worker.drain(max_seconds=3600.0)
        if not state.vectors.missing():
            break
    missing = state.vectors.missing()
    if missing:
        raise SearchEvalError(
            f"{len(missing)} filed documents have no vectors: a recording is missing"
        )
    state.searcher.keyword.rebuild()
    ids: dict[str, str] = {}
    for item in _items(state):
        if item.state == "filed" and item.document_id and item.sha256 in by_key:
            ids.setdefault(by_key[item.sha256].doc.doc_id, item.document_id)
    return state, ids, entries


def build_search_vault(split: Split, recordings: Path, root: Path, embedder: Embedder) -> AppState:
    """The vault of a split, indexed and ready to search."""
    return _build(search_vault_docs(split), recordings, root, embedder)[0]


def _secrets(entries: Sequence[_Entry]) -> list[str]:
    known = [MASTER_PASSWORD]
    for e in entries:
        number = e.doc.fields.get("number")
        if e.doc.doc_type is DocType.card_front and isinstance(number, str):
            known.append(number)
    return known


def _scan(state: AppState, entries: Sequence[_Entry]) -> tuple[list[str], int]:
    waiting = {
        i.rel_path: i.sha256
        for i in state.store.items(["asked", "held", "waiting_secrets"])
        if i.rel_path is not None and i.rel_path.startswith(f"{INBOX}/")
    }
    hits = scan_outputs(
        state.vault,
        state.settings.db_path,
        state.settings.log_dir,
        _secrets(entries),
        waiting_originals=waiting,
    )
    return hits, len(waiting_original_paths(state.vault, waiting))


# -- judging one question -------------------------------------------------------------------------


@dataclass
class Result:
    """What the app returned for one prompt."""

    query: Query | None  # None when the reading was off
    rows: Rows
    outcome: Answer | NoAnswer | None
    quick: Rows


@dataclass
class SearchRow:
    """One question's numbers and booleans. The prompt is the eval's own synthetic question."""

    id: str
    kind: str
    origin: str
    style: str
    prompt: str
    top1: bool | None = None
    top3: bool | None = None
    quick_top3: bool | None = None
    answered: bool | None = None
    answer_correct: bool | None = None
    citation_ok: bool | None = None
    list_reading: bool | None = None
    list_precision: float | None = None
    list_recall: float | None = None
    declined: bool | None = None
    reading_off: bool = False
    backstop_conflicts: int = 0
    cause: str | None = None
    slots: list[str] = field(default_factory=list)
    seconds_quick: float = 0.0
    seconds_full: float = 0.0


def _canon_item(item: object) -> str:
    if isinstance(item, dict):
        return json.dumps({str(k): _canon_item(v) for k, v in sorted(item.items())})
    text = str(item).strip()
    try:
        return format(Decimal(text).normalize(), "f")
    except InvalidOperation:
        return normalise("text", text)


def _canon(kind: str, value: JsonValue) -> object:
    if value is None:
        return None
    try:
        if kind == "date":
            return parse_date(value)
        if kind == "amount":
            return parse_amount(value if isinstance(value, str) else Decimal(str(value)))
    except (ValueError, InvalidOperation):
        return ("unreadable", str(value))
    if kind == "list":
        items = (
            value if isinstance(value, list) else [p for p in str(value).split(";") if p.strip()]
        )
        return sorted(_canon_item(i) for i in items)
    return normalise(kind, str(value))  # type: ignore[arg-type]


def same_value(kind: str, truth: JsonValue, got: JsonValue) -> bool:
    """Whether a stored value is the truth, each read by the field's kind."""
    return _canon(kind, truth) == _canon(kind, got)


_PART = re.compile(r"(?:^|(?<=\. ))([^:]+?): (yes, until|ended) \d{1,2} \w{3} \d{4}\.")


def stated_status(text: str) -> dict[str, bool] | None:
    """The status an answer's text states: `{"valid": ...}` for a validity answer, or each
    part's name to whether its cover holds for a warranty answer."""
    if text.startswith("Yes, until"):
        return {"valid": True}
    if text.startswith("Ended"):
        return {"valid": False}
    parts = {
        m.group(1).strip().casefold(): m.group(2) == "yes, until" for m in _PART.finditer(text)
    }
    return parts or None


def _status_matches(want: Mapping[str, bool], text: str) -> bool:
    said = stated_status(text)
    folded = {k.casefold(): v for k, v in want.items()}
    return said == folded


def _answer_right(q: Question, answer: Answer, truth: Mapping[str, SynthDoc]) -> bool:
    if answer.field != q.field or q.field is None:
        return False
    doc = truth[q.targets[0]]
    schema = SCHEMAS[doc.doc_type]
    kind = field_kind(schema, q.field) if q.field in schema.model_fields else "text"
    if not same_value(kind, q.value, answer.value):
        return False
    return q.status is None or _status_matches(q.status, answer.text)


def _cited(
    q: Question, answer: Answer, truth: Mapping[str, SynthDoc], back: Mapping[str, str]
) -> bool:
    """The answer's document is a target and one cited line is on the truth page and overlaps the
    truth box with IoU 0.5 or more."""
    tid = back.get(answer.document_id)
    if tid is None or tid not in q.targets or q.field is None:
        return False
    page, box = _where(truth[tid], q.field)
    if page is None or box is None:
        return False
    return any(ref.page == page and iou(ref.bbox, box) >= IOU_MIN for ref in answer.lines)


def _types(query: Query) -> set[DocType]:
    return set(query.types) | {t for t, area in AREA.items() if area in query.areas}


def query_differences(got: Query, want: Query) -> list[str]:
    """The slots on which a resolved query differs from the truth (empty: it reads right)."""
    out: list[str] = []
    if got.intent != want.intent:
        out.append("intent")
    if set(got.people) != set(want.people):
        out.append("people")
    if _types(got) != _types(want):
        out.append("types")
    if got.role != want.role:
        out.append("role")
    if got.range != want.range:
        out.append("range")
    if normalise_name(got.place or "") != normalise_name(want.place or ""):
        out.append("place")
    return out


def declined(res: Result) -> bool:
    """The app gave no answer: a NoAnswer, a person it could not read, no rows, or thin evidence
    (the `weak_match` rule `compose` applies)."""
    if isinstance(res.outcome, NoAnswer):
        return True
    query = res.query
    if query is not None and any(u.startswith("person:") for u in query.unread):
        return True
    if not res.rows:
        return True
    return query is not None and weak_match(query, res.rows)


def _lookup_cause(q: Question, res: Result, ids: Sequence[str]) -> str | None:
    query = res.query
    if query is None:
        return "reading off"
    if query.intent != "lookup" or query.field != q.field:
        return "reading misread"
    if not ids or ids[0] not in q.targets:
        return "retrieval miss"
    outcome = res.outcome
    if isinstance(outcome, NoAnswer):
        return {
            "weak_match": "weak match declined",
            "unknown_person": "unknown person",
            "no_field": "field not on the type",
            "not_on_page": "no located line",
        }.get(outcome.reason, "retrieval miss")
    return "wrong value"


def judge(
    q: Question,
    res: Result,
    truth: Mapping[str, SynthDoc],
    back: Mapping[str, str],
) -> SearchRow:
    """The numbers for one question. `truth` is the vault's documents by id and `back` maps a
    database document id to its truth id."""
    row = SearchRow(q.id, q.kind, q.origin, q.style, q.prompt, reading_off=res.query is None)
    row.backstop_conflicts = res.query.backstop_conflicts if res.query else 0
    ids = [back.get(r.document_id, r.document_id) for r in res.rows]
    quick = [back.get(r.document_id, r.document_id) for r in res.quick]
    targets = set(q.targets)
    if q.kind in ("lookup", "find"):
        row.top1 = bool(ids) and ids[0] in targets
        row.top3 = any(i in targets for i in ids[:3])
        row.quick_top3 = any(i in targets for i in quick[:3])
        row.declined = declined(res)
        if not row.top1:
            row.cause = "reading off" if res.query is None else "retrieval miss"
            if res.query is not None and q.kind == "find" and res.query.intent == "list":
                row.cause = "reading misread"
    if q.kind == "lookup" and q.field is not None:
        answer = res.outcome if isinstance(res.outcome, Answer) else None
        row.answered = answer is not None
        row.answer_correct = answer is not None and _answer_right(q, answer, truth)
        if answer is not None:
            row.citation_ok = _cited(q, answer, truth, back)
        if not row.answer_correct:
            row.cause = _lookup_cause(q, res, ids)
    if q.kind == "list" and q.query is not None:
        if res.query is None:
            row.list_reading, row.cause = False, "reading off"
        else:
            row.slots = query_differences(res.query, q.query)
            row.list_reading = not row.slots
            if row.slots:
                row.cause = "list slot wrong"
        got, want = set(ids), set(q.expected or [])
        row.list_precision = len(got & want) / len(got) if got else 0.0
        row.list_recall = len(got & want) / len(want) if want else 1.0
        if row.list_reading and (row.list_precision < 1.0 or row.list_recall < 1.0):
            row.cause = "retrieval miss"
    if q.kind == "none":
        row.declined = declined(res)
        if not row.declined:
            row.cause = "not declined"
    return row


# -- running --------------------------------------------------------------------------------------


def _full(
    state: AppState, prompt: str, reader: PromptReader, today: date
) -> tuple[Query | None, Rows, Answer | NoAnswer | None]:
    """The full search as the route runs it: read the prompt, then list or look up."""
    try:
        parsed = read_prompt(prompt, reader)
    except ModelUnavailable:
        return None, state.searcher.quick(prompt), None
    query = resolve(parsed, state.household, today, prompt, state.searcher.place_values())
    if query.intent == "list":
        rows = state.searcher.list(query)
        sentence(query, state.household, today)
        return query, rows, None
    rows = state.searcher.lookup(query, prompt)
    return query, rows, compose(query, rows, state.store, today)


def run_search(
    split: Split,
    reader: PromptReader,
    embedder: Embedder,
    recordings: Path,
    root: Path,
    *,
    docs: Sequence[SynthDoc] | None = None,
    questions: Sequence[Question] | None = None,
    facts: dict[str, Any] | None = None,
) -> list[SearchRow]:
    """Build the vault, ask every question (quick search, then the full one, each timed) and
    scan what the run wrote. `facts` receives the run's counts and leak-scan result."""
    vault_docs = list(docs) if docs is not None else search_vault_docs(split)
    asked = list(questions) if questions is not None else load_questions(split)
    state, ids, entries = _build(vault_docs, recordings, root, embedder)
    back = {v: k for k, v in ids.items()}
    truth = {d.doc_id: d for d in vault_docs}
    rows: list[SearchRow] = []
    try:
        for q in asked:
            t0 = time.perf_counter()
            quick = state.searcher.quick(q.prompt)
            t1 = time.perf_counter()
            query, found, outcome = _full(state, q.prompt, reader, EVAL_TODAY)
            t2 = time.perf_counter()
            row = judge(q, Result(query, found, outcome, quick), truth, back)
            row.seconds_quick, row.seconds_full = t1 - t0, t2 - t1
            rows.append(row)
        hits, skipped = _scan(state, entries)
        if facts is not None:
            filed = sum(1 for d in vault_docs if d.doc_id in ids)
            facts.update(
                {
                    "documents": len(vault_docs),
                    "filed": filed,
                    "expected_filed_but_not": sum(
                        1 for d in vault_docs if not d.expected_ask and d.doc_id not in ids
                    ),
                    "secrets_found": len(hits),
                    "secret_hits": hits[:20],
                    "waiting_originals_skipped": skipped,
                    "vectors_missing": getattr(embedder, "missing_queries", 0),
                }
            )
    finally:
        state.gate.lock()
        state.store.conn.close()
    return rows


# -- summary --------------------------------------------------------------------------------------


def _mean(values: Sequence[bool | float | None]) -> tuple[float | None, int]:
    kept = [float(v) for v in values if v is not None]
    return (sum(kept) / len(kept) if kept else None), len(kept)


def _percentile(values: Sequence[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(math.ceil(p * len(ordered)) - 1, 0)]


_METRICS = (
    "top1",
    "top3",
    "quick_top3",
    "answer_correct",
    "citation_ok",
    "list_reading",
    "list_precision",
    "list_recall",
)


def summarise_search(
    rows: Sequence[SearchRow], facts: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Every metric overall and by origin: `{"top1": {"all": ..., "eval-v1": ..., "extra": ...}}`
    with the number of questions behind each under `n`. Seconds are the median and the 95th
    percentile with the first question (the cold start) left out and reported apart."""
    groups: dict[str, list[SearchRow]] = {"all": list(rows)}
    for origin in ORIGINS:
        groups[origin] = [r for r in rows if r.origin == origin]
    out: dict[str, Any] = {"questions": len(rows), "kinds": dict(Counter(r.kind for r in rows))}
    n: dict[str, dict[str, int]] = {}

    def put(name: str, pick: Any) -> None:
        pairs = {g: _mean([pick(r) for r in rs]) for g, rs in groups.items()}
        out[name] = {g: v for g, (v, _) in pairs.items()}
        n[name] = {g: c for g, (_, c) in pairs.items()}

    for name in _METRICS:
        put(name if name != "citation_ok" else "citation_accuracy", lambda r, k=name: getattr(r, k))
    put("answered", lambda r: r.answered)
    put("declined_when_none", lambda r: r.declined if r.kind == "none" else None)
    put(
        "declined_when_answerable",
        lambda r: r.declined if r.kind in ("lookup", "find") else None,
    )
    out["readings_missing"] = sum(1 for r in rows if r.reading_off)
    out["backstop_conflicts"] = sum(r.backstop_conflicts for r in rows)
    warm = list(rows[1:])
    picks: dict[str, Callable[[SearchRow], float]] = {
        "seconds_quick": lambda r: r.seconds_quick,
        "seconds_full": lambda r: r.seconds_full,
    }
    for name, pick in picks.items():
        stats: dict[str, Any] = {}
        for g in groups:
            values = [pick(r) for r in warm if g == "all" or r.origin == g]
            stats[g] = {
                "median": _percentile(values, 0.5),
                "p95": _percentile(values, 0.95),
                "n": len(values),
            }
        out[name] = stats
    if rows:
        out["cold_first_seconds"] = {
            "quick": rows[0].seconds_quick,
            "full": rows[0].seconds_full,
        }
    out["n"] = n
    out["causes"] = dict(Counter(r.cause for r in rows if r.cause))
    out.update(facts or {})
    return out


def row_dicts(rows: Sequence[SearchRow]) -> list[dict[str, Any]]:
    return [asdict(r) for r in rows]


# -- the smoke set --------------------------------------------------------------------------------


def smoke_documents() -> list[SynthDoc]:
    """The 22 smoke documents of eval-v1 (val)."""
    from evals.recordings import load_smoke

    wanted = set(load_smoke(EVAL_V1))
    return [d for d in load_set(EVAL_V1) if d.doc_id in wanted]


def smoke_questions(docs: Sequence[SynthDoc]) -> list[Question]:
    """The val lookups and finds whose every target is a smoke photo, then ten list prompts
    written for this small vault."""
    ids = {d.doc_id for d in docs}
    household = load_household(EVAL_V1 / "household.json")
    about = [
        q
        for q in load_questions("val")
        if q.kind in ("lookup", "find") and q.targets and set(q.targets) <= ids
    ]
    lists = _list_questions(docs, household, "val", EVAL_TODAY, SET_SEED)[:N_SMOKE_LISTS]
    return [*about, *lists]


def write_smoke_questions(folder: Path = SMOKE_DIR) -> list[Question]:
    qs = smoke_questions(smoke_documents())
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "questions.jsonl").write_text("".join(q.model_dump_json() + "\n" for q in qs))
    return qs


def load_smoke_questions(folder: Path = SMOKE_DIR) -> list[Question]:
    lines = (folder / "questions.jsonl").read_text().splitlines()
    return [Question.model_validate_json(line) for line in lines if line]


def origin_counts(docs: Collection[SynthDoc]) -> dict[str, int]:
    return dict(Counter(origin_of(d) for d in docs))
