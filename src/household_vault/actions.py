"""What the owner can do about a file: answer a question, discard, keep both, retry, unlock a
locked PDF, and Undo a filing. The words of every error are shown to the owner as they are.

An answer never files anything itself. It is saved on the item (its `overrides`) and the item goes
back to the queue through `Store.requeue`; the worker's job files it or asks the next question.
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Sequence
from typing import Any

from pydantic import JsonValue

from household_vault.activity import Activity, Step
from household_vault.db import Item, ItemState, StateChanged, Store
from household_vault.doctypes import DocType
from household_vault.filing.cardness import is_card_item
from household_vault.filing.filer import BUSY, Filer, UndoError
from household_vault.filing.names import DEFAULT_NAME, scrub_identifiers
from household_vault.filing.questions import AnswerKind
from household_vault.people import Household
from household_vault.reading.pipeline import CARD_FIELD_TYPES, scrub_card_fields
from household_vault.reading.render import DamagedFileError, LockedPdfError, page_count
from household_vault.reasons import Reason
from household_vault.schemas import SCHEMAS
from household_vault.schemas._coerce import field_kind, secret_fields
from household_vault.schemas.parse import parse_fields
from household_vault.secrets.gate import SecretsGate
from household_vault.secrets.store import SecretsLocked
from household_vault.vaultroot import VaultGone, VaultPathError
from household_vault.worker import Worker

CARD_NOT_RETYPED = "This was read as a bank card. Discard it, or upload the card in the app."
_ANSWERABLE: frozenset[ItemState] = frozenset({"asked", "held"})
log = logging.getLogger(__name__)
_GONE_COPY = "The other copy is no longer there. Nothing was deleted."
_CHANGED = "This file changed while you were answering. Look at it again"
_UPLOADED = (
    "This card came from an upload. To change it, delete the filed copy and upload it again. "
    "Nothing was changed."
)
_TAKEN = "A file with that name is already in Inbox. Move or rename it, then try Undo again."


class AnswerError(Exception):
    """An answer that cannot be used. The message is shown to the owner as it is."""


class PartlyAnswered(AnswerError):
    """Some of several files were refused. `answered` were queued; `refused` maps each refused
    item id to the reason, in words for the owner."""

    def __init__(self, answered: list[Item], refused: dict[int, str]) -> None:
        super().__init__(
            f"{len(refused)} of {len(answered) + len(refused)} files were not answered"
        )
        self.answered = answered
        self.refused = refused


class Actions:
    def __init__(
        self,
        worker: Worker,
        filer: Filer,
        store: Store,
        activity: Activity,
        household: Household,
        gate: SecretsGate | None = None,
    ) -> None:
        self.gate = gate
        self.worker = worker
        self.filer = filer
        self.store = store
        self.activity = activity
        self.household = household
        self._unlock_lock = threading.Lock()

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
            doc_type = self._doc_type(value)
            if is_card_item(item) and doc_type not in CARD_FIELD_TYPES:
                raise AnswerError(CARD_NOT_RETYPED)
            overrides["doc_type"] = doc_type.value
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
        """Say whose several files are (a person id, or `home`). A file that cannot be answered
        (it changed meanwhile) does not stop the others: `PartlyAnswered` names those refused."""
        self._person(value)
        answered: list[Item] = []
        refused: dict[int, str] = {}
        for item_id in item_ids:
            try:
                answered.append(self.answer(item_id, "person", value))
            except AnswerError as exc:
                refused[item_id] = str(exc)
        if refused:
            raise PartlyAnswered(answered, refused)
        return answered

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
        if doc_type is DocType.other:
            raise AnswerError("Choose what kind of document it is")
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
        assert raw_type is not None  # a schema was found for it
        card_area = DocType(raw_type) in CARD_FIELD_TYPES
        if card_area and field == "last4" and not re.fullmatch(r"\d{4}", value.strip()):
            raise AnswerError("Type only the last four digits of the card")
        raw: Any = value
        if field_kind(schema, field) == "list":
            raw = [part.strip() for part in value.split(",") if part.strip()]
        parsed = parse_fields(schema, {field: raw}, mode=self.worker.settings.mode)
        dumped = parsed.model.model_dump(mode="json")[field]
        if card_area:  # a typed answer is scrubbed like a read one: no card number, anywhere
            dumped = scrub_card_fields({field: dumped}, None, DocType(raw_type))[field]
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

    def other_copy_path(self, item: Item) -> str | None:
        """Where the file this one copies is now, checked live against the vault, or None when
        it is gone or the item is not a copy."""
        if Reason.duplicate in item.reasons:
            for d in self.store.filed_with_sha(item.sha256):
                if self._holds(d.rel_path, item.sha256):
                    return d.rel_path
            live = self.store.items_with_sha(
                item.sha256, ["asked", "held", "queued", "waiting_secrets"]
            )
            # An item whose old file name this file took over is not a second copy.
            for o in live:
                if (
                    o.id != item.id
                    and o.rel_path is not None
                    and o.rel_path != item.rel_path
                    and self._holds(o.rel_path, item.sha256)
                ):
                    return o.rel_path
            return None
        if Reason.possible_copy in item.reasons:
            other_id = item.overrides.get("copy_of")
            other = self.store.document(other_id) if isinstance(other_id, str) else None
            if other is not None and self._holds(other.rel_path, other.sha256):
                return other.rel_path
        return None

    def _another_copy_remains(self, item: Item) -> bool:
        """Before a copy is deleted: the file it copies must still be there with the same content,
        in the filed folder or as another item waiting in the vault."""
        if Reason.duplicate in item.reasons or Reason.possible_copy in item.reasons:
            return self.other_copy_path(item) is not None
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

    def _save_password(self, item: Item, password: str, master_password: str | None) -> None:
        """Keep the PDF's password in the secrets store, which the master password opens. The
        password was checked against the PDF first, so a wrong one is never saved."""
        assert self.gate is not None
        if not master_password:
            raise AnswerError("Enter the master password to save this password")
        try:
            self.gate.unlock(master_password)
        except SecretsLocked:
            raise AnswerError("That master password did not open the secrets store") from None
        title = f"PDF password: {scrub_identifiers(item.original_name) or DEFAULT_NAME}"
        try:
            self.gate.store().add_pdf_password(title, password)
        except Exception as exc:  # a full disk, Drive away: nothing is said about the password
            log.warning("could not save a PDF password: %s", type(exc).__name__)
            raise AnswerError("The password could not be saved. Nothing was changed.") from None

    # -- Undo ----------------------------------------------------------------------------------

    def undo_document(self, doc_id: str) -> Item:
        doc = self.store.document(doc_id)
        if doc is not None and doc.secret_ref is not None and self.gate is not None:
            return self._undo_card(doc.id, doc.secret_ref)
        try:
            return self.filer.undo(doc_id)
        except FileExistsError:
            raise UndoError(_TAKEN) from None

    def _undo_card(self, doc_id: str, secret_ref: str) -> Item:
        """Put the original photo back in Inbox from its attachment in the store, which needs
        the secrets store open. The entry stays, so a refile reuses it."""
        assert self.gate is not None
        doc = self.store.document(doc_id)
        if doc is not None and self.store.item(doc.item_id).origin == "upload":
            raise UndoError(_UPLOADED)
        try:
            secrets = self.gate.store()
            names = secrets.attachment_names(secret_ref)
            if not names:
                raise KeyError(secret_ref)
            original = secrets.attachment(secret_ref, names[0])
        except SecretsLocked:
            raise UndoError(
                "Unlock the secrets store to undo a card. Nothing was changed."
            ) from None
        except KeyError:
            raise UndoError(
                "The original photo is not in the secrets store. Nothing was changed."
            ) from None
        try:
            return self.filer.undo_card(doc_id, original, names[0].rpartition(".")[2])
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
        if save and self.gate is None:
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
        if save:
            self._save_password(item, password, master_password)
        # The password goes in first, so the job that starts at once finds it. If the file moved
        # on, put back what was there, but only if the entry is still the one stored here.
        with self._unlock_lock:
            passwords = self.worker.pending_passwords
            before = passwords.get(item.id)
            passwords[item.id] = password
            try:
                self.store.requeue(item.id, from_states=_ANSWERABLE)
            except StateChanged:
                if passwords.get(item.id) == password:
                    if before is None:
                        passwords.pop(item.id, None)
                    else:
                        passwords[item.id] = before
                raise AnswerError(_CHANGED) from None
        self.activity.record(
            item.id,
            Step.unlocked,
            "unlocked",
            "Unlocked with the password you gave",
            file=item.rel_path,
        )
        return self.store.item(item.id)
