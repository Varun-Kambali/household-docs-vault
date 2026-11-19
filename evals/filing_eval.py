"""The filing eval: the real worker, filer and secrets gate on a temporary vault, with the
recorded readings of a split.

Each variant (clean, photo, scan, locked) gets its own fresh vault, so the variants of one base
never meet and are never possible copies of each other. Every document is dropped in `Inbox`
(a card with a back is uploaded, as the app takes it), the worker runs, and what ended up where
is compared with what the reading eval's decision said. Metric definitions: `evals/README.md`.
"""

from __future__ import annotations

import json
import shutil
from collections import Counter
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, get_args

from vault_synth.model import SynthDoc
from vault_synth.sets import locked_password

from evals.reading_eval import load_documents, read_and_decide
from evals.recordings import files_as_filed
from household_vault.app_state import AppState, build_app_state
from household_vault.config import Settings, load_settings
from household_vault.db import DocumentRow, Item, ItemState
from household_vault.doctypes import DocType
from household_vault.filing.decide import Decision
from household_vault.leakscan import scan_outputs, waiting_original_paths
from household_vault.people import load_household
from household_vault.reading.engines import Engines, PageReader
from household_vault.reading.lines import PageText
from household_vault.reading.recorded import recorded_engines
from household_vault.reading.source import DocumentSource, document_key
from household_vault.reasons import Reason
from household_vault.vaultroot import INBOX, RECORDS, VaultGone

MASTER_PASSWORD = "synthetic-master-password"
VARIANTS = ("clean", "photo", "scan", "locked")
UNDO_COUNT = 3
_ALL_STATES: tuple[ItemState, ...] = get_args(ItemState)


class MaskedCopyPages:
    """The recorded page reader, plus one stand-in. The filer reads a masked card copy again to
    check that the number cannot be read; that copy is made during the run, so no recording of it
    exists. A key that belongs to no document of the split is such a copy, and reads as a page
    with no lines, a perfectly masked card. Mask quality itself is pinned by Task 20's tests on
    pixels. A document of the split with no recording still raises `ModelUnavailable`."""

    def __init__(self, inner: PageReader, known_keys: Collection[str]) -> None:
        self.inner = inner
        self.known = frozenset(known_keys)

    def read_pages(
        self, source: DocumentSource, sha256: str, password: str | None
    ) -> list[PageText]:
        if sha256 in self.known:
            return self.inner.read_pages(source, sha256, password)
        return [PageText(page=0, width=1000, height=700, lines=[])]


@dataclass
class _Entry:
    """One document of the vault: its truth, its files, the decision the reading eval makes."""

    doc: SynthDoc
    files: list[bytes]
    key: str
    expected: Decision


@dataclass
class _Vault:
    variant: str
    state: AppState
    entries: list[_Entry]
    copied: set[str] = field(default_factory=set)  # keys of the documents that got a copy
    undo: dict[str, int] = field(default_factory=dict)


def _settings(root: Path, recordings: Path) -> Settings:
    for sub in ("logs", "db"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    env = {
        "VAULT_ROOT": str(root / "vault"),
        "VAULT_DB": str(root / "db" / "vault.db"),
        "VAULT_HOUSEHOLD": str(root / "household.json"),
        "VAULT_LOG_DIR": str(root / "logs"),
        "VAULT_READER": "recorded",
        "VAULT_RECORDINGS": str(recordings.absolute()),
    }
    return load_settings(env=env).model_copy(update={"settle_seconds": 0.0})


def _copy_name(name: str) -> str:
    stem, dot, ext = name.rpartition(".")
    return f"{stem} (1).{ext}" if dot else f"{name} (1)"


def _items(state: AppState) -> list[Item]:
    return state.store.items(_ALL_STATES)


def _drop(state: AppState, name: str, data: bytes) -> None:
    state.vault.write_atomic(f"{INBOX}/{name}", data)


def _unlock_all(state: AppState, by_key: dict[str, _Entry]) -> None:
    """Give each locked file its password, as the owner would, then let the worker go on."""
    for item in state.store.items(["asked"]):
        entry = by_key.get(item.sha256)
        if Reason.locked in item.reasons and entry is not None:
            state.actions.unlock(item.id, locked_password(entry.doc.base_id))
    state.worker.drain()


def _prepare(
    variant: str, docs: Sequence[SynthDoc], set_dir: Path, engines: Engines
) -> list[_Entry]:
    household = load_household(set_dir / "household.json")
    entries: list[_Entry] = []
    for doc in docs:
        if doc.variant != variant:
            continue
        files = files_as_filed([(set_dir / name).read_bytes() for name in doc.files])
        _, decision, _ = read_and_decide(doc, files, engines, household)
        entries.append(_Entry(doc, files, document_key(files), decision))
    return entries


def _run_vault(
    variant: str,
    entries: list[_Entry],
    set_dir: Path,
    root: Path,
    recordings: Path,
    engines: Engines,
) -> _Vault:
    settings = _settings(root, recordings)
    shutil.copy(set_dir / "household.json", settings.household_path)
    known = {e.key for e in entries}
    state = build_app_state(
        settings, engines=Engines(MaskedCopyPages(engines.pages, known), engines.models)
    )
    vault = _Vault(variant, state, entries)
    by_key = {e.key: e for e in entries}
    has_cards = any(e.doc.doc_type is DocType.card_front for e in entries)
    if has_cards:
        state.gate.create(MASTER_PASSWORD)
        state.gate.lock()  # single card photos wait in Inbox until the store is opened
    singles = [e for e in entries if len(e.files) == 1]
    for e in singles:
        _drop(state, e.doc.files[0], e.files[0])
    # An exact copy of every tenth file that would be filed (a card photo is replaced by its
    # masked copy, so a second photo of it is not a copy of a filed file). The first copy goes in
    # with the originals, the next in a later pass, and so on in turn. In the clean vault the
    # first three go to the Undo step and get no copy, because a document that is held as a
    # copy's twin would be held again when it is filed a second time.
    fileable = [
        e
        for e in singles
        if e.expected.outcome == "file" and e.doc.doc_type is not DocType.card_front
    ]
    pool = fileable[UNDO_COUNT:] if variant == "clean" else fileable
    now_copies: list[_Entry] = []
    later_copies: list[_Entry] = []
    for n, e in enumerate(pool[::10]):
        # A locked PDF dropped twice in one pass ends with both held as duplicates of each other
        # once it is unlocked (see the README), so its copy always arrives after the unlock.
        (now_copies if n % 2 == 0 and variant != "locked" else later_copies).append(e)
    for e in now_copies:
        vault.copied.add(e.key)
        _drop(state, _copy_name(e.doc.files[0]), e.files[0])
    state.worker.drain()
    if has_cards:
        state.gate.unlock(MASTER_PASSWORD)
        state.worker.drain()
        for e in (e for e in entries if len(e.files) > 1):
            state.cards.upload(e.files, MASTER_PASSWORD)
    _unlock_all(state, by_key)
    for e in later_copies:
        vault.copied.add(e.key)
        _drop(state, _copy_name(e.doc.files[0]), e.files[0])
    state.worker.drain()
    if variant == "clean":
        _undo_and_retry(vault)
    return vault


def _row_of(state: AppState, item: Item | None) -> DocumentRow | None:
    return state.store.document(item.document_id) if item and item.document_id else None


def _filed_item(state: AppState, entry: _Entry) -> Item | None:
    """The item of the document that was filed. When a copy was dropped beside it, either file
    may be the one the worker took first; the other is held as a duplicate. With none filed, the
    first item of the document."""
    found = [i for i in _items(state) if i.sha256 == entry.key]
    filed = [i for i in found if i.state == "filed"]
    return (filed or found)[0] if found else None


def _undo_and_retry(vault: _Vault) -> None:
    """Undo three filed documents, retry them, and note which came back to the same path."""
    state = vault.state
    chosen: list[tuple[str, str, int]] = []
    for e in vault.entries:
        item = _filed_item(state, e)
        row = _row_of(state, item)
        if row is None or row.secret_ref is not None:
            continue  # a card's Undo needs the secrets store and is pinned by Task 20
        chosen.append((row.id, row.rel_path, row.item_id))
        if len(chosen) == UNDO_COUNT:
            break
    for doc_id, _, _ in chosen:
        state.actions.undo_document(doc_id)
    for _, _, item_id in chosen:
        state.actions.retry(item_id)
    state.worker.drain()
    vault.undo = {"tried": len(chosen), "same_path": 0}
    for _, path, item_id in chosen:
        again = _row_of(state, state.store.item(item_id))
        if again is not None and again.rel_path == path:
            vault.undo["same_path"] += 1


def _placement(vault: _Vault) -> tuple[int, int]:
    """(documents filed where the reading eval's decision said, documents it said to file)."""
    wanted = matched = 0
    for e in vault.entries:
        if e.expected.outcome != "file":
            continue
        wanted += 1
        row = _row_of(vault.state, _filed_item(vault.state, e))
        if (
            row is not None
            and e.expected.folder is not None
            and row.owner == e.expected.owner
            and row.rel_path.startswith(f"{e.expected.folder}/")
        ):
            matched += 1
    return wanted, matched


def _copies_caught(vault: _Vault) -> tuple[int, int]:
    """(copies dropped, copies caught). A copy is caught when its file ended filed once and
    every other file with the same content is held as a duplicate."""
    caught = 0
    items = _items(vault.state)
    for key in vault.copied:
        same = [i for i in items if i.sha256 == key]
        filed = [i for i in same if i.state == "filed"]
        rest = [i for i in same if i.state != "filed"]
        if (
            len(filed) == 1
            and rest
            and all(i.state == "asked" and Reason.duplicate in i.reasons for i in rest)
        ):
            caught += 1
    return len(vault.copied), caught


def _wrong_merges(vault: _Vault) -> int:
    """Documents held as a duplicate or a possible copy though no copy of them was dropped. Each
    vault holds one variant of each base, so any such hold is against a different document."""
    return sum(
        1
        for i in _items(vault.state)
        if i.sha256 not in vault.copied
        and i.state == "asked"
        and {Reason.duplicate, Reason.possible_copy} & set(i.reasons)
    )


def _cvv_rows(vault: _Vault) -> int:
    """Rows and record files that hold a value for `cvv`."""
    state = vault.state
    found = sum(
        1
        for row in (_row_of(state, i) for i in _items(state))
        if row is not None and row.fields.get("cvv") not in (None, "")
    )
    try:
        names = [e.name for e in state.vault.list_dir(RECORDS) if e.kind == "file"]
    except VaultGone:  # no records folder yet: nothing was filed here
        names = []
    for name in names:
        record = json.loads(state.vault.read_bytes(f"{RECORDS}/{name}").decode("utf-8"))
        if (record.get("fields") or {}).get("cvv") not in (None, ""):
            found += 1
    return found


def _secrets(entries: Sequence[_Entry]) -> list[str]:
    known = [MASTER_PASSWORD]
    for e in entries:
        number = e.doc.fields.get("number")
        if e.doc.doc_type is DocType.card_front and isinstance(number, str):
            known.append(number)
        if e.doc.variant == "locked":
            known.append(locked_password(e.doc.base_id))
    return known


def _is_card(item: Item) -> bool:
    """A card that is asked about stays in Inbox, because its unmasked photo never moves to
    Needs a look."""
    return (item.reading or {}).get("doc_type") == DocType.card_front.value


def _waiting_originals(state: AppState) -> dict[str, str]:
    """Path and hash of each original that waits in `Inbox` on the owner's answer."""
    waiting: set[ItemState] = {"asked", "held", "waiting_secrets"}
    return {
        i.rel_path: i.sha256
        for i in state.store.items(sorted(waiting))
        if i.rel_path is not None and i.rel_path.startswith(f"{INBOX}/")
    }


def _leftover_in_inbox(vault: _Vault) -> int:
    state = vault.state
    left = 0
    for entry in state.vault.list_dir(INBOX):
        if entry.kind != "file":
            continue
        item = state.store.item_at(f"{INBOX}/{entry.name}")
        in_place = item is not None and item.state == "asked" and _is_card(item)
        if item is None or not (item.state == "held" or in_place):
            left += 1
    return left


def run_filing(
    set_dir: Path,
    split: str,
    recordings: Path,
    workdir: Path,
    *,
    only: Collection[str] | None = None,
) -> dict[str, Any]:
    """Run one fresh vault per variant over the split and report what the worker did."""
    docs = load_documents(set_dir, split, only)
    engines = recorded_engines(recordings)
    totals: Counter[str] = Counter()
    secret_hits: list[str] = []
    per_variant: dict[str, dict[str, int]] = {}
    started = datetime.now().astimezone().isoformat(timespec="seconds")
    for variant in VARIANTS:
        entries = _prepare(variant, docs, set_dir, engines)
        if not entries:
            continue
        vault = _run_vault(variant, entries, set_dir, workdir / variant, recordings, engines)
        try:
            wanted, matched = _placement(vault)
            copies, caught = _copies_caught(vault)
            state = vault.state
            waiting = _waiting_originals(state)
            hits = scan_outputs(
                state.vault,
                state.settings.db_path,
                state.settings.log_dir,
                _secrets(entries),
                waiting_originals=waiting,
            )
            skipped = len(waiting_original_paths(state.vault, waiting))
            firsts = [(_filed_item(state, e), e) for e in entries]
            asked = [(i, e) for i, e in firsts if i is not None and i.state == "asked"]
            counts = {
                "documents": len(entries),
                "should_file": wanted,
                "filed_as_decided": matched,
                "copies": copies,
                "copies_caught": caught,
                "wrong_merges": _wrong_merges(vault),
                "secrets_found": len(hits),
                "waiting_originals_skipped": skipped,
                "cvv_stored": _cvv_rows(vault),
                "asked": len(asked),
                "asked_though_clean": sum(1 for _, e in asked if not e.doc.expected_ask),
                "expected_clean": sum(1 for e in entries if not e.doc.expected_ask),
                "inbox_left": _leftover_in_inbox(vault),
                "undo_tried": vault.undo.get("tried", 0),
                "undo_same_path": vault.undo.get("same_path", 0),
            }
        finally:
            vault.state.gate.lock()
            vault.state.store.conn.close()
        secret_hits += [f"{variant}: {h}" for h in hits]
        per_variant[variant] = counts
        totals.update(counts)
    return _report(totals, per_variant, started, secret_hits)


def _share(hits: int, total: int) -> float:
    return hits / total if total else 1.0


def _report(
    totals: Counter[str],
    per_variant: dict[str, dict[str, int]],
    started: str,
    secret_hits: list[str],
) -> dict[str, Any]:
    documents = totals["documents"]
    return {
        "started": started,
        "documents": documents,
        "placement_matches_decision": _share(totals["filed_as_decided"], totals["should_file"]),
        "documents_placed": totals["filed_as_decided"],
        "exact_copies": totals["copies"],
        "undo_tried": totals["undo_tried"],
        "exact_copies_caught": _share(totals["copies_caught"], totals["copies"]),
        "wrong_merges": totals["wrong_merges"],
        "secrets_found": totals["secrets_found"],
        "waiting_originals_skipped": totals["waiting_originals_skipped"],
        # masked descriptions only (the last four digits of a number, never a value)
        "secret_hits": secret_hits[:20],
        "cvv_stored": totals["cvv_stored"],
        "needs_a_look_share": {
            "expected_clean": _share(totals["asked_though_clean"], totals["expected_clean"])
            if totals["expected_clean"]
            else 0.0,
            "all": _share(totals["asked"], documents) if documents else 0.0,
        },
        "inbox_left": totals["inbox_left"],
        "undo_same_path": _share(totals["undo_same_path"], totals["undo_tried"]),
        "by_variant": per_variant,
    }
