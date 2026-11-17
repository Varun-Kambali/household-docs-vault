"""What the owner can do about a file: answer a question, discard, keep both, retry, unlock a
locked PDF, and Undo a filing. The words of every error are shown to the owner as they are.

An answer never files anything itself. It is saved on the item (its `overrides`) and the item goes
back to the queue through `Store.requeue`; the worker's job files it or asks the next question.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic import JsonValue

from household_vault.activity import Activity, Step
from household_vault.db import Item, ItemState, StateChanged, Store
from household_vault.doctypes import DocType
from household_vault.filing.filer import BUSY, Filer, UndoError
from household_vault.filing.questions import AnswerKind
from household_vault.people import Household
from household_vault.reading.render import DamagedFileError, LockedPdfError, page_count
from household_vault.reasons import Reason
from household_vault.schemas import SCHEMAS
from household_vault.schemas._coerce import field_kind, secret_fields
from household_vault.schemas.parse import parse_fields
from household_vault.vaultroot import VaultGone, VaultPathError
from household_vault.worker import Worker

_ANSWERABLE: frozenset[ItemState] = frozenset({"asked", "held"})
_GONE_COPY = "The other copy is no longer there. Nothing was deleted."
_CHANGED = "This file changed while you were answering. Look at it again"
_TAKEN = "A file with that name is already in Inbox. Move or rename it, then try Undo again."


class AnswerError(Exception):
    """An answer that cannot be used. The message is shown to the owner as it is."""


class Actions:
    def __init__(
        self, worker: Worker, filer: Filer, store: Store, activity: Activity, household: Household
    ) -> None:
        self.worker = worker
        self.filer = filer
        self.store = store
        self.activity = activity
        self.household = household

    # -- answers -------------------------------------------------------------------------------

    def answer(self, item_id: int, kind: AnswerKind, value: str, field: str | None = None) -> Item:
        if kind == "unlock":
            return self.unlock(item_id, value)
        item = self._answerable(item_id)
        if kind == "discard" or (kind == "copy" and value == "discard"):
            return self._discard(item)
        overrides: dict[str, Any] = dict(item.overrides)
        if kind == "person":
            overrides["owner"] = self._person(value)
        elif kind == "type":
            overrides["doc_type"] = self._doc_type(value).value
            overrides["reread"] = True
        elif kind == "field":
            name, parsed = self._field(item, field, value)
            overrides["fields"] = {**(overrides.get("fields") or {}), name: parsed}
        elif kind == "copy":
            if value != "keep_both":
                raise AnswerError("Choose to keep both or to discard this one")
            overrides["keep_copy"] = True
            return self._requeue(item, overrides, "process", Step.kept_both, "keep_both")
        elif kind == "retry":
            overrides["reread"] = True
        else:  # pragma: no cover - AnswerKind is closed
            raise AnswerError("That answer is not one I know")
        return self._requeue(item, overrides, "refile", Step.answered, kind)

    def answer_many(self, item_ids: Sequence[int], value: str) -> list[Item]:
        """Say whose several files are (a person id, or `home`). All are checked before any
        is changed."""
        self._person(value)
        for item_id in item_ids:
            self._answerable(item_id)
        return [self.answer(item_id, "person", value) for item_id in item_ids]

    def retry(self, item_id: int) -> Item:
        """Try a held or asked file again from the start."""
        item = self._answerable(item_id)
        overrides = {**item.overrides, "reread": True}
        return self._requeue(item, overrides, "refile", Step.retried, "retry")

    def _answerable(self, item_id: int) -> Item:
        try:
            item = self.store.item(item_id)
        except KeyError:
            raise AnswerError("That file is not in the list any more") from None
        if item.state in BUSY or item.state in ("queued", "reading"):
            raise AnswerError("This file is being worked on. Try again in a moment")
        if item.state not in _ANSWERABLE:
            raise AnswerError("This file is not waiting for an answer")
        return item

    def _person(self, value: str) -> str:
        if value != "home" and all(p.id != value for p in self.household.people):
            raise AnswerError("That person is not in the household")
        return value

    @staticmethod
    def _doc_type(value: str) -> DocType:
        try:
            doc_type = DocType(value)
        except ValueError:
            raise AnswerError("That kind of document is not one I know") from None
        if doc_type is DocType.visit_recording:
            raise AnswerError("Recordings are filed by the medical step, not by a type answer")
        return doc_type

    def _field(self, item: Item, field: str | None, value: str) -> tuple[str, JsonValue]:
        raw_type = item.overrides.get("doc_type") or (item.reading or {}).get("doc_type")
        schema = SCHEMAS.get(DocType(raw_type)) if raw_type else None
        if schema is None or field is None or field not in schema.model_fields:
            raise AnswerError("That is not a field of this document")
        if field in secret_fields(schema):
            raise AnswerError("Card numbers are added from a photo, not typed")
        raw: Any = value
        if field_kind(schema, field) == "list":
            raw = [part.strip() for part in value.split(",") if part.strip()]
        parsed = parse_fields(schema, {field: raw}, mode=self.worker.settings.mode)
        dumped = parsed.model.model_dump(mode="json")[field]
        if field in parsed.issues or dumped in (None, "", []):
            label = field.replace("_", " ")
            raise AnswerError(f"That is not something I can use for the {label}")
        return field, dumped

    def _requeue(
        self, item: Item, overrides: dict[str, Any], kind: Any, step: Step, what: str
    ) -> Item:
        try:
            with self.store.transaction():
                self.store.update_item(item.id, overrides=overrides)
                self.store.requeue(item.id, kind, from_states=_ANSWERABLE)
        except StateChanged:
            raise AnswerError(_CHANGED) from None
        self.activity.record(item.id, step, what, f"Answered: {what}", file=item.rel_path)
        return self.store.item(item.id)

    def _holds(self, rel: str | None, sha256: str) -> bool:
        """True when a regular file at rel has exactly this content."""
        if rel is None:
            return False
        try:
            return self.filer.vault.sha256(rel) == sha256
        except VaultPathError:
            return False

    def _another_copy_remains(self, item: Item) -> bool:
        """Before a copy is deleted: the file it copies must still be there with the same content,
        in the filed folder or as another item waiting in the vault."""
        if Reason.duplicate in item.reasons:
            if any(
                self._holds(d.rel_path, item.sha256) for d in self.store.filed_with_sha(item.sha256)
            ):
                return True
            live = self.store.items_with_sha(
                item.sha256, ["asked", "held", "queued", "waiting_secrets"]
            )
            # An item whose old file name this file took over is not a second copy.
            return any(
                o.id != item.id
                and o.rel_path != item.rel_path
                and self._holds(o.rel_path, item.sha256)
                for o in live
            )
        if Reason.possible_copy in item.reasons:
            other_id = item.overrides.get("copy_of")
            other = self.store.document(other_id) if isinstance(other_id, str) else None
            return other is not None and self._holds(other.rel_path, other.sha256)
        return True

    def _discard(self, item: Item) -> Item:
        """Delete the file wherever it waits (in Drive it goes to Drive's trash), unless it is a
        copy and the file it copies is gone."""
        with self.filer.lock:
            current = self.store.item(item.id)
            if current.state not in _ANSWERABLE:
                raise AnswerError(_CHANGED)
            if not self._another_copy_remains(current):
                raise AnswerError(_GONE_COPY)
            try:
                self.store.update_item_if(item.id, _ANSWERABLE, state="discarded", rel_path=None)
            except StateChanged:
                raise AnswerError(_CHANGED) from None
            if current.rel_path is not None:
                try:
                    self.filer.vault.unlink(current.rel_path)
                except VaultGone:
                    pass
                except Exception:
                    self.store.update_item(item.id, state=current.state, rel_path=current.rel_path)
                    raise
            self.activity.record(
                item.id,
                Step.discarded,
                "discarded",
                "Discarded at your request",
                file=current.rel_path,
            )
        self.activity.backfill_csv()
        return self.store.item(item.id)

    # -- Undo ----------------------------------------------------------------------------------

    def undo_document(self, doc_id: str) -> Item:
        try:
            return self.filer.undo(doc_id)
        except FileExistsError:
            raise UndoError(_TAKEN) from None

    def undo_item(self, item_id: int) -> Item:
        """Take a file out of Needs a look and hold it in Inbox."""
        try:
            return self.filer.undo_needs_a_look(item_id)
        except FileExistsError:
            raise UndoError(_TAKEN) from None
        except (ValueError, KeyError):
            raise UndoError(
                "This file is not waiting in Needs a look. Nothing was changed."
            ) from None

    # -- unlocking -----------------------------------------------------------------------------

    def unlock(
        self,
        item_id: int,
        password: str,
        save: bool = False,
        master_password: str | None = None,
    ) -> Item:
        """Open a locked PDF with its password. The password is kept in memory for the one job
        that reads the file, and nowhere else."""
        if save:
            raise AnswerError("Saving passwords comes with the secrets store")
        item = self._answerable(item_id)
        if Reason.locked not in item.reasons or item.rel_path is None:
            raise AnswerError("This file is not waiting for a password")
        try:
            page_count(self.filer.vault.read_bytes(item.rel_path), password)
        except LockedPdfError:
            raise AnswerError("That password did not open the PDF") from None
        except DamagedFileError:
            raise AnswerError("This file could not be opened as a PDF") from None
        except VaultPathError:
            raise AnswerError("The file is no longer there") from None
        # The password goes in first, so the job that starts at once finds it.
        self.worker.pending_passwords[item.id] = password
        try:
            self.store.requeue(item.id, from_states=_ANSWERABLE)
        except StateChanged:
            self.worker.pending_passwords.pop(item.id, None)
            raise AnswerError(_CHANGED) from None
        self.activity.record(
            item.id,
            Step.unlocked,
            "unlocked",
            "Unlocked with the password you gave",
            file=item.rel_path,
        )
        return self.store.item(item.id)
