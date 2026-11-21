"""The filer: copy a document into its folder, verify the copy, record it, then clear `Inbox`.

Nothing here deletes or overwrites a file except one step: the `Inbox` copy is removed after the
filed copy has been verified by its SHA-256 and the database knows about it, and only while it
is still the file that was copied.

Every move of a file follows one pattern, so a stop at any point is finished or rolled back by
`recover` from the database and the files alone:

1. One commit writes the intent: the item's state (`filing`, `undoing` or `moving`), `target`
   (where the file is going) and `pending` (what is needed to finish: the SHA-256, and for a
   filing the decision, secret reference, extra fields and the new document's id and time).
2. The file is copied or moved. Nothing is ever replaced.
3. One transaction records the outcome (the document row, or its removal) with the item's final
   state and the activity row.
4. The `Inbox` copy of a filing is removed last, only if it still has the copied content.

An ordinary exception before step 3 of a filing rolls the copy back and is raised to the worker.
After step 3 the document is filed: a failure to clear `Inbox` is logged, not raised, and
`recover` clears it later. A stop of the process (not an exception) keeps the intent for `recover`.
"""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import logging
import threading
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any

from pydantic import JsonValue

from household_vault.activity import Activity, Step
from household_vault.db import Item, ItemState, Store
from household_vault.doctypes import DocType
from household_vault.filing import records
from household_vault.filing.cardness import is_card_photo, mark_card
from household_vault.filing.decide import Decision
from household_vault.filing.names import clean_component, filed_name
from household_vault.filing.questions import Question
from household_vault.filing.records import (
    LONG_RUN_TYPES,
    DocumentRecord,
    build_record,
    check_extra_fields,
    decision_from_json,
    decision_to_json,
    record_path,
    record_rows,
    stored_reading,
)
from household_vault.intake.sniff import EXTENSION, FileKind
from household_vault.people import Household
from household_vault.reading.pipeline import Reading
from household_vault.reasons import Reason
from household_vault.search.index import KeywordIndex
from household_vault.vaultroot import (
    INBOX,
    NEEDS_A_LOOK,
    VaultGone,
    VaultPathError,
    VaultRoot,
)

log = logging.getLogger(__name__)

# A file in one of these states is being worked on or is done: the filer will not start on it.
BUSY: frozenset[ItemState] = frozenset(
    {"filing", "filed_pending_clear", "undoing", "moving", "filed"}
)
_FILING_KEYS = frozenset(
    {"doc_id", "created_at", "sha256", "decision", "secret_ref", "extra_fields"}
)


class UndoError(Exception):
    """Undo was refused. The message is shown to the owner as it is."""


class CardPhotoError(ValueError):
    """The file is a card photo: only its masked copy may be filed."""


class TargetGone(Exception):
    """The folder a copy was going into vanished (Drive, or the owner). The source is fine and
    nothing was changed; the job can be tried again."""


def _suffix_of(path: str) -> str:
    return PurePosixPath(path).suffix


class Filer:
    def __init__(
        self,
        vault: VaultRoot,
        store: Store,
        activity: Activity,
        household: Household,
        clock: Callable[[], datetime],
    ) -> None:
        self.vault = vault
        self.store = store
        self.activity = activity
        self.household = household
        self.clock = clock
        # Held around every move of a file, here and by callers that remove an Inbox photo.
        self.lock = threading.Lock()

    # -- filing --------------------------------------------------------------------------------

    def file(
        self,
        item: Item,
        reading: Reading,
        decision: Decision,
        secret_ref: str | None = None,
        extra_fields: Mapping[str, JsonValue] | None = None,
    ) -> DocumentRecord:
        """File the item's own file. `CopyMismatch`, `VaultGone` (the source is gone),
        `TargetGone` and any other exception leave the item and the vault as they were; a stop
        of the process is finished by `recover`."""
        if item.rel_path is None:
            raise ValueError("this item has no file in the vault; use file_new for made bytes")
        with self.lock:
            return self._file(
                item, self._extension(item), reading, decision, secret_ref, extra_fields, None
            )

    def file_new(
        self,
        item: Item,
        data: bytes,
        ext: str,
        reading: Reading,
        decision: Decision,
        secret_ref: str | None,
        extra_fields: Mapping[str, JsonValue] | None = None,
    ) -> DocumentRecord:
        """File bytes the app made (the masked card copy). The item's own file is never touched:
        for an Inbox card the caller removes the photo afterwards (under `lock`)."""
        if is_card_photo(self.store, hashlib.sha256(data).hexdigest()):
            raise CardPhotoError("only the masked copy of a card may be filed as made bytes")
        with self.lock:
            return self._file(item, ext, reading, decision, secret_ref, extra_fields, data)

    def _file(
        self,
        item: Item,
        ext: str,
        reading: Reading,
        decision: Decision,
        secret_ref: str | None,
        extra_fields: Mapping[str, JsonValue] | None,
        data: bytes | None,
    ) -> DocumentRecord:
        item = self._idle(item)
        if data is None and is_card_photo(self.store, item.sha256):
            raise CardPhotoError("the raw bytes of a card photo are never filed")
        if decision.outcome != "file" or decision.folder is None or decision.owner is None:
            raise ValueError("a decision that asks a question cannot be filed")
        self._check_people(decision)
        effective = self._effective_type(item, reading)
        if effective is None:
            raise ValueError("a document without a type cannot be filed")
        extra = dict(extra_fields or {})
        check_extra_fields(effective, extra)
        name = filed_name(decision.doc_date, decision.description, ext)
        try:
            self.vault.mkdirs(decision.folder)
            target = f"{decision.folder}/{self.vault.free_name(decision.folder, name)}"
        except VaultGone as exc:
            raise TargetGone("the folder for this document cannot be made") from exc
        sha = item.sha256 if data is None else hashlib.sha256(data).hexdigest()
        pending: dict[str, Any] = {
            "doc_id": uuid.uuid4().hex,
            "created_at": self.clock().isoformat(),
            "sha256": sha,
            "decision": decision_to_json(decision),
            "secret_ref": secret_ref,
            "extra_fields": extra,
            "new": data is not None,
        }
        stored = stored_reading(reading, card_item=effective in LONG_RUN_TYPES)
        before = item.state
        self.store.update_item(
            item.id, state="filing", target=target, pending=pending, reading=stored
        )
        try:
            if data is None:
                assert item.rel_path is not None
                self.vault.copy_verified(item.rel_path, target, sha)
            else:
                self._write_bytes(target, data)
        except FileExistsError:
            # Something else took the name first, even identical bytes: never ours to adopt.
            self._abandon(item.id, before, target)
            raise
        except VaultGone as exc:
            self._abandon(item.id, before, target)
            if data is None and item.rel_path is not None and not self.vault.exists(item.rel_path):
                raise  # the file itself is gone
            raise TargetGone("the folder for this document is gone") from exc
        except Exception:
            self._abandon(item.id, before, target)
            raise
        try:
            record = self._commit(item.id)
        except Exception:
            self._roll_back(item.id, before, target, sha, pending["doc_id"])
            raise
        self._clear_quietly(item.id)
        return record

    def _write_bytes(self, target: str, data: bytes) -> None:
        folder, _, name = target.rpartition("/")
        partial = f"{folder}/.{name}.partial"
        self.vault.write_atomic(partial, data)
        self.vault.move(partial, target)

    def _abandon(self, item_id: int, before: ItemState, target: str) -> None:
        """The copy did not happen: drop the partial and the intent. The target is not touched."""
        self._remove_partials(target)
        self.store.update_item(item_id, state=before, target=None, pending=None)

    def _roll_back(
        self, item_id: int, before: ItemState, target: str, sha: str, doc_id: str
    ) -> None:
        """The copy is in place but the filing cannot be recorded: remove what this filing made
        and restore the item. If a file cannot be removed the intent stays, so `recover`
        finishes the filing rather than losing track of the copy."""
        try:
            if self._ours(target, sha):
                self.vault.unlink(target)
            with contextlib.suppress(VaultPathError):
                self.vault.unlink(record_path(doc_id))
        except Exception as exc:
            log.warning("could not roll back filing of item %s: %s", item_id, type(exc).__name__)
            return
        self.store.update_item(item_id, state=before, target=None, pending=None)

    def _commit(self, item_id: int) -> DocumentRecord:
        """Step 3 from the item row alone, so a restart runs the same code: the record file,
        then one transaction with the document and the state `filed_pending_clear`."""
        item = self.store.item(item_id)
        pending, target = item.pending, item.target
        if pending is None or target is None:
            raise ValueError(f"item {item_id} has no filing under way")
        record = build_record(
            item,
            item.reading or {},
            decision_from_json(pending["decision"]),
            target,
            pending["secret_ref"],
            datetime.fromisoformat(pending["created_at"]),
            pending["extra_fields"],
            doc_id=pending["doc_id"],
            sha256=pending["sha256"],
        )
        records.write_record(self.vault, record)
        row, people, pages = record_rows(record)
        with self.store.transaction():
            if self.store.document(record.id) is None:
                self.store.add_document(row, people, pages)
                KeywordIndex(self.store).add(record.id)
            self.store.update_item(item_id, state="filed_pending_clear", document_id=record.id)
        return record

    def _clear_quietly(self, item_id: int) -> None:
        """Step 4 after the document is filed: a failure here is not a failed filing."""
        try:
            self._finish_clear(self.store.item(item_id))
        except Exception as exc:
            log.warning(
                "could not clear the Inbox copy of item %s: %s", item_id, type(exc).__name__
            )
            with contextlib.suppress(Exception):
                self.activity.record(
                    item_id,
                    Step.error,
                    "clear_failed",
                    f"The Inbox copy could not be removed yet: {type(exc).__name__}",
                )

    def _finish_clear(self, item: Item) -> bool:
        """Remove the `Inbox` copy and mark the item filed, when the filed copy verifies and the
        `Inbox` file is still the one that was copied. True when the item is now `filed`."""
        doc = self.store.document(item.document_id) if item.document_id else None
        if doc is None or not self._ours(doc.rel_path, doc.sha256):
            return False  # keep the Inbox copy: the filed one is not there as recorded
        made = bool((item.pending or {}).get("new"))
        if not made and item.rel_path is not None and self._ours(item.rel_path, item.sha256):
            with contextlib.suppress(VaultGone):
                self.vault.unlink(item.rel_path)
        with self.store.transaction():
            self.store.update_item(item.id, state="filed", target=None, pending=None)
            self.activity.record(
                item.id, Step.filed, "filed", f"Filed as {doc.description}", file=doc.rel_path
            )
        self.activity.backfill_csv()
        return True

    def clear_card_photo(self, item_id: int) -> bool:
        """Remove the `Inbox` photo of a filed card, under the filer's lock, only while it is
        still the file that was photographed. True when it was removed."""
        with self.lock:
            item = self.store.item(item_id)
            if item.state != "filed" or item.document_id is None:
                return False
            with contextlib.suppress(VaultGone):
                return self._clear_card_photo(item)
            self.store.update_item(item.id, rel_path=None)  # it vanished by itself
            return False

    # -- Needs a look, Undo --------------------------------------------------------------------

    def to_needs_a_look(
        self, item: Item, reasons: list[Reason], question: Question, reading: Reading | None
    ) -> Item:
        with self.lock:
            item = self._idle(item)
            if item.rel_path is None:
                raise ValueError("this item has no file in the vault to move")
            stored = None
            if reading is not None:
                effective = self._effective_type(item, reading)
                stored = stored_reading(reading, card_item=effective in LONG_RUN_TYPES)
            columns: dict[str, Any] = {
                "reasons": reasons,
                "question": dataclasses.asdict(question),
                "reading": stored,
            }
            card = is_card_photo(self.store, item.sha256)
            if card:  # a card photo is asked about where it is, never moved
                mark_card(self.store, item)
            if card or item.rel_path.startswith(f"{NEEDS_A_LOOK}/"):  # the file stays
                with self.store.transaction():
                    self.store.update_item(item.id, state="asked", **columns)
                    self.activity.record(
                        item.id,
                        Step.needs_a_look,
                        "needs_a_look",
                        question.text,
                        file=item.rel_path,
                    )
                self.activity.backfill_csv()
                return self.store.item(item.id)
            name = self.vault.free_name(NEEDS_A_LOOK, PurePosixPath(item.rel_path).name)
            self._move(item, item.rel_path, f"{NEEDS_A_LOOK}/{name}", "moving", "asked", columns)
            return self.store.item(item.id)

    def undo(self, doc_id: str) -> Item:
        """Move a filed document back to `Inbox` and hold it. Refused, with nothing changed, when
        the filed copy is not at its recorded path with its recorded content any more."""
        with self.lock:
            doc = self.store.document(doc_id)
            if doc is None:
                raise UndoError(f"There is no filed document {doc_id}. Nothing was changed.")
            if doc.secret_ref is not None:
                raise UndoError("Undo for cards needs the secrets store. Nothing was changed.")
            if not self._ours(doc.rel_path, doc.sha256):
                raise UndoError(
                    f"The filed copy is no longer at {doc.rel_path}. Nothing was changed."
                )
            item = self.store.item(doc.item_id)
            if item.state != "filed":
                raise UndoError("This document is still being filed. Nothing was changed.")
            dest = self._inbox_path(item, _suffix_of(doc.rel_path))
            self._move(
                item,
                doc.rel_path,
                dest,
                "undoing",
                "held",
                {},
                {"doc_id": doc_id, "sha256": doc.sha256},
            )
            return self.store.item(item.id)

    def undo_card(self, doc_id: str, original: bytes, ext: str) -> Item:
        """Undo a filed card: write the original photo (from its attachment in the secrets
        store) to `Inbox` as a held file, and remove the masked copy and the record. The
        store entry stays and `secret_ref` stays in the item's overrides, so a refile reuses
        it. Refused, with nothing changed, when the masked copy is not as it was filed."""
        with self.lock:
            doc = self.store.document(doc_id)
            if doc is None or doc.secret_ref is None:
                raise UndoError(f"There is no filed card {doc_id}. Nothing was changed.")
            if not self._ours(doc.rel_path, doc.sha256):
                raise UndoError(
                    f"The filed copy is no longer at {doc.rel_path}. Nothing was changed."
                )
            item = self.store.item(doc.item_id)
            if item.origin == "upload":  # there is no Inbox photo, and none may be written
                raise UndoError("This card came from an upload. Nothing was changed.")
            if item.state != "filed":
                raise UndoError("This document is still being filed. Nothing was changed.")
            dest = self._inbox_path(item, f".{ext}")
            original_sha = hashlib.sha256(original).hexdigest()
            before = dataclasses.replace(item)
            pending = {
                "from": doc.rel_path,
                "sha256": doc.sha256,
                "final": "held",
                "doc_id": doc_id,
                "card": True,
                "item_sha256": original_sha,
            }
            self.store.update_item(
                item.id,
                state="undoing",
                target=dest,
                rel_path=dest,
                pending=pending,
                overrides={**item.overrides, "secret_ref": doc.secret_ref},
            )
            try:
                self._write_bytes(dest, original)
            except Exception:
                self._remove_partials(dest)
                if not self._ours(dest, original_sha):
                    self._restore(before)
                    raise
            self._finish_move(item.id)
            return self.store.item(item.id)

    def _restore(self, before: Item) -> None:
        self.store.update_item(
            before.id,
            state=before.state,
            rel_path=before.rel_path,
            target=before.target,
            pending=before.pending,
            overrides=before.overrides,
        )

    def undo_needs_a_look(self, item_id: int) -> Item:
        with self.lock:
            item = self.store.item(item_id)
            if item.state != "asked" or item.rel_path is None:
                raise ValueError(f"item {item_id} is not waiting in {NEEDS_A_LOOK}")
            dest = self._inbox_path(item, _suffix_of(item.rel_path))
            self._move(item, item.rel_path, dest, "moving", "held", {})
            return self.store.item(item_id)

    def _move(
        self,
        item: Item,
        src: str,
        dest: str,
        state: ItemState,
        final: ItemState,
        columns: dict[str, Any],
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Move a file with its intent saved first (see the module note). While the file is in
        flight the item claims whichever of the two paths is in `Inbox`, so the watcher does
        not take it for a new file."""
        pending = {"from": src, "sha256": item.sha256, "final": final, **(extra or {})}
        claim = dest if dest.startswith(f"{INBOX}/") else src
        self.store.update_item(
            item.id, state=state, target=dest, rel_path=claim, pending=pending, **columns
        )
        try:
            self.vault.move(src, dest)
        except Exception:
            if not self._ours(dest, pending["sha256"]):  # nothing was placed: put the item back
                self.store.update_item(
                    item.id,
                    state=item.state,
                    rel_path=item.rel_path,
                    target=item.target,
                    pending=item.pending,
                    reasons=item.reasons,
                    question=item.question,
                    reading=item.reading,
                )
            raise  # a file that was placed keeps its intent; `recover` finishes the move
        self._finish_move(item.id)

    def _finish_move(self, item_id: int) -> None:
        """The last step of a move, from the item row alone: for an Undo the record file goes;
        then one transaction with the document row's removal, the final state and the activity."""
        item = self.store.item(item_id)
        pending, dest = item.pending, item.target
        if pending is None or dest is None:
            raise ValueError(f"item {item_id} has no move under way")
        doc_id = pending.get("doc_id")
        if doc_id:
            with contextlib.suppress(VaultGone):
                self.vault.unlink(record_path(doc_id))
        if pending.get("card"):  # the masked copy goes; the original is back in Inbox
            with contextlib.suppress(VaultGone):
                self.vault.unlink(pending["from"])
        changes: dict[str, Any] = {
            "state": pending["final"],
            "rel_path": dest,
            "target": None,
            "pending": None,
        }
        if doc_id:
            changes.update(sha256=pending.get("item_sha256", pending["sha256"]), document_id=None)
        with self.store.transaction():
            if doc_id:
                KeywordIndex(self.store).remove(doc_id)
                self.store.remove_document(doc_id)
            self.store.update_item(item_id, **changes)
            if doc_id or pending["final"] == "held":
                self.activity.record(
                    item_id, Step.undone, "undone", "Moved back to Inbox", file=dest
                )
            else:
                text = (item.question or {}).get("text", "")
                self.activity.record(item_id, Step.needs_a_look, "needs_a_look", text, file=dest)
        self.activity.backfill_csv()

    # -- recovery ------------------------------------------------------------------------------

    def recover(self) -> list[int]:
        """Finish or roll back what a stop left half done. Returns the ids it changed."""
        touched: list[int] = []
        with self.lock:
            for item in self.store.items(["filing"]):
                if self._guarded(item, self._recover_filing):
                    touched.append(item.id)
            for item in self.store.items(["filed_pending_clear"]):
                if self._guarded(item, self._finish_clear):
                    touched.append(item.id)
            for item in self.store.items(["undoing", "moving"]):
                if self._guarded(item, self._recover_move):
                    touched.append(item.id)
            for item in self._filed_card_items():
                if self._guarded(item, self._clear_card_photo):
                    touched.append(item.id)
        return list(dict.fromkeys(touched))

    def _guarded(self, item: Item, step: Callable[[Item], bool | None]) -> bool:
        """Run one recovery step; a failure is logged and leaves the item as it was."""
        try:
            return step(item) is not False
        except Exception as exc:
            log.warning("recovery of item %s failed: %s", item.id, type(exc).__name__)
            self.activity.record(
                item.id, Step.error, "recover_failed", f"Recovery stopped: {type(exc).__name__}"
            )
            return False

    def _recover_filing(self, item: Item) -> bool:
        target, pending = item.target, item.pending
        if (
            target
            and pending
            and pending.keys() >= _FILING_KEYS
            and self._ours(target, pending["sha256"])
        ):
            self._remove_partials(target)  # a stop right after a hard link leaves one behind
            self._commit(item.id)
            self._finish_clear(self.store.item(item.id))
            return True
        # Not linked (or not ours): the partial copy goes and the item is read again. A file at
        # the target that this filing did not make is left alone.
        if target:
            self._remove_partials(target)
        if pending and pending.get("doc_id"):
            with contextlib.suppress(VaultPathError):
                self.vault.unlink(record_path(pending["doc_id"]))
        with self.store.transaction():
            self.store.update_item(item.id, target=None, pending=None)
            self.store.requeue(item.id)
        return True

    def _recover_move(self, item: Item) -> bool:
        """Finish a move by the content of the two paths: only the source has it, move it; both
        have it (a hard-link stop), remove the source; only the destination, it is done."""
        pending, dest = item.pending, item.target
        if pending is None or dest is None or "from" not in pending:
            raise ValueError("no move to finish")
        if pending.get("card"):
            return self._recover_card_undo(item, pending, dest)
        src, sha = pending["from"], pending["sha256"]
        at_dest, at_src = self._ours(dest, sha), self._ours(src, sha)
        if at_dest and at_src:
            self.vault.unlink(src)
        elif at_src:
            if self.vault.exists(dest):  # the name was taken by other bytes during the stop
                folder, _, name = dest.rpartition("/")
                free = f"{folder}/{self.vault.free_name(folder, name)}"
                claimed = item.rel_path == dest
                self.store.update_item(
                    item.id, target=free, **({"rel_path": free} if claimed else {})
                )
                dest = free
            self.vault.move(src, dest)
        elif not at_dest:
            if self.vault.exists(src):
                # other bytes were put at the source during the stop: this item's file is lost,
                # and the new one at that name is a file of its own, read on the next scan
                self.store.update_item(item.id, state="gone", target=None, pending=None)
                self.activity.record(
                    item.id,
                    Step.gone,
                    "gone",
                    "The file was replaced while the app was stopped, so nothing was filed",
                    file=src,
                )
                return True
            raise ValueError("neither the source nor the destination holds the file")
        self._finish_move(item.id)
        return True

    def _recover_card_undo(self, item: Item, pending: dict[str, Any], dest: str) -> bool:
        """A card Undo that was stopped: with the original in `Inbox` it is finished (the masked
        copy goes); without it the card stays filed, because the original can only come from
        the secrets store, which a restart does not have open."""
        if self._ours(dest, pending["item_sha256"]):
            self._finish_move(item.id)
            return True
        self._remove_partials(dest)
        with self.store.transaction():
            self.store.update_item(item.id, state="filed", rel_path=None, target=None, pending=None)
        return True

    def _filed_card_items(self) -> list[Item]:
        """Filed card items whose Inbox photo may still be there (ruling 19)."""
        with self.store.lock:
            ids = [
                r[0]
                for r in self.store.conn.execute(
                    "select i.id from items i join documents d on d.id = i.document_id"
                    " where i.state = 'filed' and i.rel_path is not null and d.doc_type = ?"
                    " and d.secret_ref is not null",
                    (DocType.card_front.value,),
                ).fetchall()
            ]
        return [self.store.item(i) for i in ids]

    def _clear_card_photo(self, item: Item) -> bool:
        if item.rel_path is None or not self._ours(item.rel_path, item.sha256):
            return False
        self.vault.unlink(item.rel_path)
        self.store.update_item(item.id, rel_path=None)
        return True

    # -- helpers -------------------------------------------------------------------------------

    def _idle(self, item: Item) -> Item:
        """The item as the database has it now; refused while it is being worked on or filed."""
        current = self.store.item(item.id)
        if current.state in BUSY:
            raise ValueError(f"item {item.id} is busy or already filed ({current.state})")
        return current

    def _check_people(self, decision: Decision) -> None:
        for person in [decision.owner, *decision.linked]:
            if person is not None and person != "home":
                try:
                    self.household.by_id(person)
                except KeyError:
                    raise ValueError(f"{person} is not in the household") from None

    def _ours(self, rel: str, sha256: str) -> bool:
        """True when a regular file at rel has exactly this content."""
        try:
            return self.vault.sha256(rel) == sha256
        except VaultPathError:  # gone, a link, a folder
            return False

    def _remove_partials(self, target: str) -> None:
        folder, _, name = target.rpartition("/")
        for leftover in (f".{name}.partial", f".{name}.tmp", f"..{name}.partial.tmp"):
            rel = f"{folder}/{leftover}"
            if self.vault.exists(rel):
                with contextlib.suppress(VaultGone):
                    self.vault.unlink(rel)

    def _inbox_path(self, item: Item, suffix: str) -> str:
        """A free name in Inbox: the file's own name when it came in, with the suffix it has now."""
        stem = clean_component(PurePosixPath(item.original_name).stem, 120)
        return f"{INBOX}/{self.vault.free_name(INBOX, stem + suffix)}"

    def _extension(self, item: Item) -> str:
        if item.kind is None:
            raise ValueError("the file's kind is not known yet")
        kind = FileKind(item.kind)
        if kind in EXTENSION:
            return EXTENSION[kind]
        return PurePosixPath(item.original_name).suffix.lower().lstrip(".")  # audio

    @staticmethod
    def _effective_type(item: Item, reading: Reading) -> DocType | None:
        """The type the document is filed as: the owner's answer first, else what was read."""
        answer = item.overrides.get("doc_type")
        return DocType(answer) if answer else reading.doc_type


__all__ = ["BUSY", "Filer", "TargetGone", "UndoError"]
