"""The card flows: a card photo dropped in the Drive Inbox, and one uploaded through the app.

A card photo is read once. The full number, the CVV and the photos go into `Secrets.kdbx` and
nowhere else; what is filed is a masked copy of the front (every digit but the last four
blacked out) in `<Person>/Cards/`, with the last four as a field. The photo left in Inbox is
removed, and Drive keeps it in its trash for 30 days, which `TRASH_NOTE` tells the owner.

Where a secret could travel, and what stops it:
- the reading holds the number in `secret_values`, which no dump, repr or log carries;
- a held reading (waiting for the gate) lives in this object's memory only;
- the masked image is made in memory and filed through the filer; the unmasked image is only
  ever an attachment in the store;
- the reading's line text is stored through `stored_reading`, which masks every long digit run
  and the CVV; a question about a card never moves the photo (it stays where it was).
"""

from __future__ import annotations

import dataclasses
import hashlib
import io
import logging
import threading
import uuid
from collections.abc import Sequence
from typing import Literal

from PIL import Image

from household_vault.activity import Activity, Step
from household_vault.checks import luhn_valid
from household_vault.db import Item, Store
from household_vault.doctypes import DocType
from household_vault.filing.decide import Decision, decide
from household_vault.filing.filer import Filer
from household_vault.filing.questions import question_for, upload_again_question
from household_vault.filing.records import DocumentRecord, stored_reading
from household_vault.intake.sniff import EXTENSION, FileKind, sniff
from household_vault.people import Household
from household_vault.reading.engines import Engines, open_image
from household_vault.reading.pipeline import MAX_VISION_PAGES, Reading, read_document
from household_vault.reading.render import page_count, render_page
from household_vault.reading.source import DocumentSource, document_key
from household_vault.reasons import Reason
from household_vault.secrets.gate import SecretsGate
from household_vault.secrets.mask import MaskError, mask_card, still_shows_number
from household_vault.secrets.store import SecretsLocked
from household_vault.vaultroot import VaultRoot
from household_vault.worker import effective_reading, overrides_of

log = logging.getLogger(__name__)

TRASH_NOTE = (
    "The card photo was removed from Inbox. Drive keeps deleted files in its trash for 30 days, "
    "so empty it there to remove the photo for good."
)
# HEIC needs a converter that writes a temporary file, and a card photo is never written
UPLOAD_KINDS = frozenset({FileKind.jpeg, FileKind.png})
MAX_UPLOAD_PHOTOS = MAX_VISION_PAGES
_JPEG_QUALITY = 92


class StillShowsNumber(MaskError):
    """The masked copy was read again and the card number can still be read in it."""


class CardUploadError(Exception):
    """The upload cannot be used. The message is shown to the owner as it is."""


def _digits(text: str | None) -> str:
    return "".join(c for c in (text or "") if c.isdigit())


def _readable(number: str) -> bool:
    return 13 <= len(number) <= 19 and luhn_valid(number)


class CardIntake:
    """Implements the worker's `CardHandler` and the app's card upload."""

    def __init__(
        self,
        gate: SecretsGate,
        vault: VaultRoot,
        filer: Filer,
        activity: Activity,
        store: Store,
        engines: Engines,
        household: Household,
    ) -> None:
        self.gate = gate
        self.vault = vault
        self.filer = filer
        self.activity = activity
        self.store = store
        self.engines = engines
        self.household = household
        # The reading of a card that waits for the gate, by item id, with the hash it was read
        # from. In memory only; dropped when the card is filed, asked about or gone.
        self._held: dict[int, tuple[str, Reading]] = {}
        self._held_lock = threading.Lock()

    def __repr__(self) -> str:
        return "CardIntake()"

    # -- the worker's handler ------------------------------------------------------------------

    def ready(self) -> bool:
        return self.gate.is_open()

    def held_reading(self, item_id: int, sha256: str) -> Reading | None:
        """The reading kept while the gate was closed, so the card is not read twice."""
        with self._held_lock:
            held = self._held.get(item_id)
        if held is None or held[0] != sha256:
            return None
        return held[1]

    def handle(
        self,
        item: Item,
        reading: Reading,
        source: DocumentSource,
        origin: Literal["inbox", "upload"],
    ) -> Literal["filed", "waiting", "asked"]:
        self._drop_stale()
        outcome = self._run(item, reading, source)
        if isinstance(outcome, DocumentRecord):
            return "filed"
        return outcome

    # -- the upload ----------------------------------------------------------------------------

    def upload(self, images: Sequence[bytes], master_password: str) -> DocumentRecord | Item:
        """Read one or two photos of a card (front, then back) in memory, keep them in the
        store and file the masked front. The photos are never written to the vault."""
        files = list(images)
        kind = self._upload_kind(files)
        self.gate.unlock(master_password)
        key = document_key(files)
        item = self.store.add_item(key, "card upload", None, self.filer.clock(), origin="upload")
        self.store.update_item(item.id, state="reading", kind=kind.value)
        try:
            source = DocumentSource(kind, images=files)
            reading = read_document(
                source,
                key,
                self.engines,
                mode=self.vault.mode,
                forced_type=DocType.card_front,
            )
            outcome = self._run(self.store.item(item.id), reading, source)
        except Exception:
            self._upload_again(item.id)
            raise
        if isinstance(outcome, DocumentRecord):
            return outcome
        if outcome == "waiting":  # the gate ran out during the call
            self._upload_again(item.id)
        return self.store.item(item.id)

    @staticmethod
    def _upload_kind(files: list[bytes]) -> FileKind:
        if not 1 <= len(files) <= MAX_UPLOAD_PHOTOS:
            raise CardUploadError("Upload one photo of the card, or two: the front, then the back.")
        kinds = {sniff(f[:64]) for f in files}
        kind = next(iter(kinds))
        if len(kinds) != 1 or kind not in UPLOAD_KINDS:
            raise CardUploadError(
                "Upload a JPEG or PNG photo (a HEIC photo can be saved as JPEG first)."
            )
        assert kind is not None
        return kind

    def _upload_again(self, item_id: int) -> None:
        self._forget(item_id)
        question = upload_again_question()
        self.store.update_item(
            item_id,
            state="asked",
            reasons=[question.reason],
            question=dataclasses.asdict(question),
        )
        self.activity.record(item_id, Step.needs_a_look, "needs_a_look", question.text)

    # -- one card ------------------------------------------------------------------------------

    def _run(
        self, item: Item, reading: Reading, source: DocumentSource
    ) -> DocumentRecord | Literal["waiting", "asked"]:
        ov = overrides_of(item)
        shown = effective_reading(reading, ov)
        number = _digits(reading.secret_values.get("number"))
        if not _readable(number):
            # A CVV with no number is the back of a card: its front has to come with it.
            context = {"why": "back_only"} if reading.secret_values.get("cvv") else {}
            return self._ask(item, [Reason.card_unreadable], reading, shown, context)
        decision = decide(
            reading,
            self.household,
            self.filer.clock().date(),
            self.store.documents_of_type(DocType.card_front),
            ov,
        )
        if decision.outcome == "ask":
            return self._ask(item, decision.reasons, reading, shown, self._context(item, decision))
        try:
            self.gate.store()
        except SecretsLocked:
            with self._held_lock:
                self._held[item.id] = (item.sha256, reading)
            return "waiting"
        try:
            # A HEIC photo was converted to PNG once, while it was read: the mask and the image
            # checks use those bytes, so `sips` writes one temporary copy of the card, not three.
            # The secrets entry and Undo keep the photo as it came (`source`).
            seen = reading.converted or source
            masked, front = self._masked_front(seen, item.sha256, number, reading)
        except StillShowsNumber:
            context = {"why": "tilted"}
            return self._ask(item, [Reason.card_unreadable], reading, shown, context)
        except (MaskError, ValueError):
            return self._ask(item, [Reason.card_unreadable], reading, shown, {})
        try:
            ref = self._entry_for(item, reading, source, decision, number, front)
        except SecretsLocked:  # the gate ran out, or the file went, while the card was read
            with self._held_lock:
                self._held[item.id] = (item.sha256, reading)
            return "waiting"
        record = self.filer.file_new(
            item,
            masked,
            EXTENSION[FileKind.jpeg],
            reading,
            decision,
            ref,
            {"last4": decision.last4},
        )
        self._forget(item.id)
        self._clear_photo(item)
        return record

    def _context(self, item: Item, decision: Decision) -> dict[str, str]:
        context: dict[str, str] = {}
        if decision.printed_names:
            context["printed"] = next(iter(decision.printed_names.values()))
        if decision.possible_copy_of:
            other = self.store.document(decision.possible_copy_of)
            if other is not None:
                context["path"] = other.rel_path
                context["date"] = other.created_at.date().isoformat()
                self.store.update_item(item.id, overrides={**item.overrides, "copy_of": other.id})
        return context

    def _ask(
        self,
        item: Item,
        reasons: list[Reason],
        reading: Reading,
        shown: Reading,
        context: dict[str, str],
    ) -> Literal["asked"]:
        """Ask in place: the item is marked asked and its photo stays where it is, so an
        unmasked card never lands in Needs a look. Only the masked reading text is stored."""
        question = question_for(reasons, shown, self.household, context)
        with self.filer.lock:
            self.store.update_item(
                item.id,
                state="asked",
                reasons=reasons,
                question=dataclasses.asdict(question),
                reading=stored_reading(reading, card_item=True),
            )
            self.activity.record(
                item.id, Step.needs_a_look, "needs_a_look", question.text, file=item.rel_path
            )
        self._forget(item.id)
        return "asked"

    # -- the secrets and the masked copy -------------------------------------------------------

    def _entry_for(
        self,
        item: Item,
        reading: Reading,
        source: DocumentSource,
        decision: Decision,
        number: str,
        front: int,
    ) -> str:
        """The store entry for this card, made once per item: its id goes into the item's
        overrides before the filing, so a filing that is stopped and read again finds it."""
        store = self.gate.store()
        current = self.store.item(item.id)
        ref = current.overrides.get("secret_ref")
        if isinstance(ref, str) and store.has_entry(ref):
            if store.entry_fields(ref).get("number") == number:
                return ref  # an earlier filing (or an Undo) made it for this card
            ref = None  # the number read now is another card's: a new entry
        if not isinstance(ref, str):
            # The id is saved before the entry is made, so a stop after the entry is on disk
            # is found again by that id and never makes a second entry.
            ref = str(uuid.uuid4())
            self.store.update_item(item.id, overrides={**current.overrides, "secret_ref": ref})
        fields = {**reading.fields, **overrides_of(current).fields}
        bank = str(fields.get("bank") or "").strip() or "Card"
        expiry = fields.get("expiry")
        holder = fields.get("holder")
        return store.add_card(
            f"{bank} card ending {decision.last4}",
            number,
            str(expiry) if expiry else None,
            reading.secret_values.get("cvv"),
            str(holder) if holder else None,
            self._photos(source, front),
            uid=ref,
        )

    @staticmethod
    def _photos(source: DocumentSource, front: int) -> list[tuple[str, bytes]]:
        files = source.images if source.images is not None else [source.data or b""]
        ext = EXTENSION[source.kind]
        order = [front, *[i for i in range(len(files)) if i != front]]
        return [(f"{'front' if n == 0 else 'back'}.{ext}", files[i]) for n, i in enumerate(order)]

    def _masked_front(
        self, source: DocumentSource, sha256: str, number: str, reading: Reading
    ) -> tuple[bytes, int]:
        """The masked JPEG of the page that holds the number, and that page's index. The page
        reader is asked again for the unmasked lines (the reading's own are masked)."""
        pages = self.engines.pages.read_pages(source, sha256, None)
        images = self._images(source)
        cvv = reading.secret_values.get("cvv")
        for index, (page, image) in enumerate(zip(pages, images, strict=False)):
            if any(number in _digits(ln.text) for ln in page.lines):
                masked = mask_card(image, page.lines, number, cvv)
                buf = io.BytesIO()
                masked.save(buf, format="JPEG", quality=_JPEG_QUALITY)
                self._check_masked(buf.getvalue(), number)
                return buf.getvalue(), index
        raise MaskError("no page holds the card number")

    def _check_masked(self, jpeg: bytes, number: str) -> None:
        """Read the masked copy with the same page reader. If the number can still be read in
        it (a tilted card the band did not cover), the copy is refused. A reader that fails is
        not a refusal: its error goes to the worker (a reader that is down defers the card), so
        a copy that was not checked is never filed."""
        pages = self.engines.pages.read_pages(
            DocumentSource(FileKind.jpeg, data=jpeg), hashlib.sha256(jpeg).hexdigest(), None
        )
        texts = [ln.text for page in pages for ln in page.lines]
        if still_shows_number(texts, number):
            raise StillShowsNumber("the masked copy still shows the number")

    @staticmethod
    def _images(source: DocumentSource) -> list[Image.Image]:
        if source.images is not None:
            return [open_image(f, source.kind) for f in source.images]
        data = source.data or b""
        if source.kind is FileKind.pdf:
            count = min(page_count(data), MAX_VISION_PAGES)
            return [render_page(data, i, dpi=200) for i in range(count)]
        return [open_image(data, source.kind)]

    # -- the Inbox photo -----------------------------------------------------------------------

    def _clear_photo(self, item: Item) -> None:
        """Remove the photo that was read, now that the masked copy is filed. A failure here is
        not a failed filing: the filer clears it again at the next start."""
        if item.rel_path is None:
            return
        try:
            removed = self.filer.clear_card_photo(item.id)
        except Exception as exc:
            log.warning(
                "could not remove the card photo of item %s: %s", item.id, type(exc).__name__
            )
            return
        if removed:
            self.activity.record(item.id, Step.secrets, "card_photo_removed", TRASH_NOTE)

    def _forget(self, item_id: int) -> None:
        with self._held_lock:
            self._held.pop(item_id, None)

    def _drop_stale(self) -> None:
        """Let go of readings whose item is no longer waiting."""
        with self._held_lock:
            ids = list(self._held)
        for item_id in ids:
            try:
                state = self.store.item(item_id).state
            except KeyError:
                state = "gone"
            if state not in ("waiting_secrets", "reading", "queued"):
                self._forget(item_id)
