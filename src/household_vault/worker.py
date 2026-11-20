"""The worker: one background loop that takes files from Inbox through the checks, the reader,
the filing decision and the filer, one job at a time (so one model-heavy step runs at a time).

Every outcome of a check or a read ends in one of three places: the document is filed, the file
waits in `Needs a look` with one question, or (for a card, until the secrets store is open) it
stays in `Inbox`. A file that is being worked on or is filed (`BUSY`) is never routed or filed
again: the filer refuses it too. Passwords for locked PDFs live only in `pending_passwords`, in
memory, and are dropped when the job ends.
"""

from __future__ import annotations

import dataclasses
import logging
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Protocol

from household_vault.activity import Activity, Step
from household_vault.config import Settings
from household_vault.db import Item, ItemState, Store
from household_vault.doctypes import LABEL, DocType
from household_vault.filing.cardness import CARD_STATES, is_card_item
from household_vault.filing.decide import Overrides, base_field, decide
from household_vault.filing.filer import BUSY, Filer, TargetGone
from household_vault.filing.questions import Question, question_for, upload_again_question
from household_vault.filing.records import stored_reading
from household_vault.intake.checks import CheckResult, check_file
from household_vault.intake.sniff import FileKind
from household_vault.intake.watcher import Settler, inbox_listing
from household_vault.reading.engines import Engines
from household_vault.reading.ollama import ModelUnavailable
from household_vault.reading.pipeline import Reading, read_document
from household_vault.reading.render import DamagedFileError, LockedPdfError
from household_vault.reading.source import DocumentSource
from household_vault.reasons import Reason
from household_vault.vaultroot import INBOX, CopyMismatch, VaultGone, VaultPathError, VaultRoot

log = logging.getLogger(__name__)

# Items are added before their file is read, so their hash is not known yet.
UNKNOWN_SHA = "0" * 64
SYSTEM = "_system"
FIRST_WAIT_SECONDS = 30
LONGEST_WAIT_SECONDS = 600
READER_DOWN = "Waiting for the reader (Ollama is not running)"
FOLDER_GONE = "Waiting for the folder to come back"
VAULT_AWAY = "Waiting for the vault folder to come back"
SECRETS_CLOSED = "Waiting for the secrets store to be unlocked"

_CHECK_REASONS: dict[str, Reason] = {
    "empty": Reason.empty_file,
    "unsupported": Reason.unsupported_type,
    "damaged": Reason.damaged,
    "locked": Reason.locked,
    "duplicate": Reason.duplicate,
}
_WHY: dict[Reason, str] = {
    Reason.empty_file: "it is empty",
    Reason.unsupported_type: "it is not a PDF or a photo",
    Reason.damaged: "it is damaged",
}
# States of a finished item for the batch count.
_FINISHED: frozenset[ItemState] = frozenset(
    {"filed", "filed_pending_clear", "asked", "gone", "discarded", "waiting_secrets", "held"}
)


class CardHandler(Protocol):
    """Reads a card photo into the secrets store and files its masked copy (Task 20)."""

    def handle(
        self,
        item: Item,
        reading: Reading,
        source: DocumentSource,
        origin: Literal["inbox", "upload"],
    ) -> Literal["filed", "waiting", "asked"]: ...

    def ready(self) -> bool: ...

    def held_reading(self, item_id: int, sha256: str) -> Reading | None:
        """The reading kept while the gate was closed (so the card is read once), or None."""
        ...


class HoldCards:
    """The handler until the secrets store exists: the file stays in `Inbox`, untouched, and the
    worker marks it `waiting_secrets` and logs why."""

    def ready(self) -> bool:
        return False

    def held_reading(self, item_id: int, sha256: str) -> Reading | None:
        return None

    def handle(
        self,
        item: Item,
        reading: Reading,
        source: DocumentSource,
        origin: Literal["inbox", "upload"],
    ) -> Literal["filed", "waiting", "asked"]:
        return "waiting"


@dataclass(frozen=True)
class Progress:
    waiting: int
    current: str | None
    step: str | None
    total_in_batch: int
    done_in_batch: int
    asked_in_batch: int
    batch_started_at: datetime | None


def overrides_of(item: Item) -> Overrides:
    """The owner's answers stored on an item, as the filing rules take them."""
    stored = item.overrides
    doc_type = stored.get("doc_type")
    return Overrides(
        doc_type=DocType(doc_type) if doc_type else None,
        owner=stored.get("owner"),
        fields=dict(stored.get("fields") or {}),
        keep_copy=bool(stored.get("keep_copy")),
    )


def effective_reading(reading: Reading, ov: Overrides) -> Reading:
    """The reading with the owner's answers applied, so a question is asked about what is still
    wrong and not about what was already answered."""
    overridden = {base_field(k) for k in ov.fields}
    return reading.model_copy(
        update={
            "doc_type": ov.doc_type or reading.doc_type,
            "fields": {**reading.fields, **ov.fields},
            "issues": {k: v for k, v in reading.issues.items() if base_field(k) not in overridden},
        }
    )


class Worker:
    def __init__(
        self,
        settings: Settings,
        vault: VaultRoot,
        store: Store,
        activity: Activity,
        engines: Engines,
        filer: Filer,
        cards: CardHandler,
        clock: Callable[[], datetime],
    ) -> None:
        self.settings = settings
        self.vault = vault
        self.store = store
        self.activity = activity
        self.engines = engines
        self.filer = filer
        self.cards = cards
        self.clock = clock
        # Passwords of locked PDFs, by item id. In memory only, dropped when the job ends.
        self.pending_passwords: dict[int, str] = {}
        self._settler = Settler(settings.settle_seconds, lambda: clock().timestamp())
        self._seen: dict[str, str] = {}
        self._secrets_tried: set[int] = set()
        self._batch_lock = threading.Lock()
        self._batch: set[int] = set()
        self._batch_open = False
        self._batch_started: datetime | None = None
        self._current: str | None = None
        self._step: str | None = None
        # When a held or waiting file was first missing from Inbox, by item id.
        self._missing_since: dict[int, tuple[datetime, int]] = {}

    # -- the loop ------------------------------------------------------------------------------

    def scan(self) -> int:
        """Queue what is new in Inbox and what can go on. Returns how many items it queued."""
        queued = 0
        try:
            listing: Mapping[str, tuple[int, int]] | None = inbox_listing(self.vault)
        except VaultGone:
            listing = self._listing_after_making_inbox()
        ready = self._settler.ready(listing) if listing is not None else []
        for name in ready:
            rel = f"{INBOX}/{name}"
            if self.store.item_at(rel) is not None:
                continue
            with self.store.transaction():
                item = self.store.add_item(UNKNOWN_SHA, name, rel, self.clock())
                self.store.enqueue(item.id, "process")
            self.activity.record(item.id, Step.noticed, "new", f"Found {name} in Inbox", file=rel)
            queued += 1
        if self.cards.ready():
            for item in self.store.items(["waiting_secrets"]):
                if item.id not in self._secrets_tried:
                    self._secrets_tried.add(item.id)
                    self.store.requeue(item.id)
                    queued += 1
        if listing is not None:
            self._notice_vanished(listing)
        self._refresh_batch()
        return queued

    def _listing_after_making_inbox(self) -> Mapping[str, tuple[int, int]] | None:
        """Inbox could not be listed. With the vault present the owner (or Drive) removed the
        folder, so it is made again; with the vault away nothing is done."""
        if not self._vault_present():
            return None
        try:
            self.vault.mkdirs(INBOX)
            return inbox_listing(self.vault)
        except VaultGone:
            return None

    def _notice_vanished(self, listing: Mapping[str, tuple[int, int]]) -> None:
        """A held, waiting or asked file that left Inbox (moved on the phone, removed in Drive)
        ends as gone, so its name is free again. Only when Inbox was listed, and only when the file
        is missing on two scans at least `settle_seconds` apart, so a sync that hides a file for
        a moment does not end it."""
        now = self.clock()
        watching = self.store.items(["held", "waiting_secrets", "asked"])
        for item in watching:
            rel = item.rel_path
            if rel is None:
                continue
            if rel.startswith(f"{INBOX}/"):
                here = rel.removeprefix(f"{INBOX}/") in listing
            else:  # Needs a look and anywhere else: by path, with the vault known to be there
                try:
                    here = self.vault.exists(rel) or not self._vault_present()
                except VaultPathError:
                    continue
            if here:
                self._missing_since.pop(item.id, None)
                continue
            since, scans = self._missing_since.get(item.id, (now, 0))
            self._missing_since[item.id] = (since, scans + 1)
            if scans + 1 >= 2 and (now - since).total_seconds() >= self.settings.settle_seconds:
                self._missing_since.pop(item.id, None)
                self._gone(item)
        live = {i.id for i in watching}
        for item_id in [i for i in self._missing_since if i not in live]:
            del self._missing_since[item_id]

    def run_once(self) -> bool:
        """Claim one job and run it. False when there is none to run."""
        self._refresh_batch()
        job = self.store.claim_next(self.clock())
        if job is None:
            return False
        deferred = False
        failed = False
        try:
            item = self.store.item(job.item_id)
            if item.state in ("queued", "reading"):
                deferred = self._run(job.id, job.kind, job.attempts, item)
        except Exception as exc:  # the job's own bookkeeping failed; the item is held
            failed = True
            self._give_up(job.item_id, exc)
        finally:
            self._current = None
            self._step = None
            if not deferred:
                self.pending_passwords.pop(job.item_id, None)
                self.store.finish(job.id, "failed" if failed else "done")
        self._refresh_batch()
        return True

    def drain(self, max_seconds: float = 600.0, stop: threading.Event | None = None) -> None:
        """Scan and run jobs until nothing is left to do, or until `stop` is set (checked
        between jobs, so a shutdown waits for the job in hand and no longer)."""
        self._seen = {}
        self._secrets_tried = set()
        deadline = time.monotonic() + max_seconds
        while time.monotonic() < deadline and not (stop is not None and stop.is_set()):
            queued = self.scan()
            ran = self.run_once()
            if not ran and not queued:
                break

    def start_up(self) -> None:
        """Finish what a stop left half done, and run again the jobs it cut off."""
        try:
            self.vault.mkdirs(SYSTEM)
        except VaultGone:
            log.warning("the vault folder is not there yet")
        self.filer.recover()
        for job in self.store.running_jobs():
            self.store.finish(job.id, "done")
            if self.store.item(job.item_id).state in ("queued", "reading"):
                self.store.requeue(job.item_id, job.kind)
        # An upload keeps its photos in memory only and has no job while it is read, so a stop
        # leaves it `reading` with nothing to run again: the owner is asked to upload it again.
        active = self._active_ids()
        for item in self.store.items(["reading", "queued"]):
            if item.origin == "upload" and item.id not in active:
                self._upload_again(item)

    def run_forever(self, stop: threading.Event) -> None:
        self.start_up()
        while not stop.is_set():
            try:
                self.drain(stop=stop)
            except Exception as exc:  # keep the loop alive; the type is all that is logged
                log.warning("the worker pass failed: %s", type(exc).__name__)
            stop.wait(self.settings.poll_seconds)

    # -- progress ------------------------------------------------------------------------------

    def _active_ids(self) -> set[int]:
        with self.store.lock:
            rows = self.store.conn.execute(
                "select distinct item_id from jobs where state in ('queued', 'running')"
            ).fetchall()
        return {r[0] for r in rows}

    def _refresh_batch(self) -> None:
        """A batch is the items queued since the queue was last empty."""
        active = self._active_ids()
        with self._batch_lock:
            if not active:
                self._batch_open = False
                return
            if not self._batch_open:
                self._batch = set()
                self._batch_started = self.clock()
                self._batch_open = True
            self._batch |= active

    def progress(self) -> Progress:
        self._refresh_batch()
        active = self._active_ids()
        with self._batch_lock:
            ids, started = set(self._batch), self._batch_started
        with self.store.lock:
            waiting = self.store.conn.execute(
                "select count(*) from jobs where state = 'queued'"
            ).fetchone()[0]
        done = asked = 0
        for item_id in ids:
            state = self.store.item(item_id).state
            if item_id not in active and state in _FINISHED:
                done += 1
                asked += state == "asked"
        return Progress(waiting, self._current, self._step, len(ids), done, asked, started)

    # -- one job -------------------------------------------------------------------------------

    def _run(self, job_id: int, kind: str, attempts: int, item: Item) -> bool:
        """Run a job. True when it was put off to run again later."""
        self.store.update_item(item.id, state="reading")
        self._current = item.original_name
        deferred = False
        try:
            if kind == "refile":
                self._refile(item)
            else:
                self._process(item)
        except ModelUnavailable:
            deferred = self._defer(job_id, attempts, item, READER_DOWN)
        except TargetGone:
            deferred = self._defer(job_id, attempts, item, FOLDER_GONE)
        except VaultGone:
            if self._vault_present():
                self._gone(self.store.item(item.id))
            else:  # Drive is away, not the file: wait for it
                deferred = self._defer(job_id, attempts, item, VAULT_AWAY)
        except CopyMismatch:
            self._copy_mismatch(kind, item)
        except Exception as exc:
            self._failed(item, exc)
        else:
            self._forget_copy_mismatches(item.id)
        finally:
            if not deferred:
                self.pending_passwords.pop(item.id, None)
        return deferred

    def _defer(self, job_id: int, attempts: int, item: Item, detail: str) -> bool:
        wait = min(FIRST_WAIT_SECONDS * 2 ** min(attempts, 10), LONGEST_WAIT_SECONDS)
        self.store.update_item(item.id, state="queued")
        self.store.defer(job_id, self.clock() + timedelta(seconds=wait))
        if attempts == 0:
            self.activity.record(item.id, Step.waiting, "waiting", detail, file=item.rel_path)
        return True

    def _vault_present(self) -> bool:
        """True when the vault folder is there and holds the app's own `_system` folder (made at
        start-up). Inbox missing alone does not mean the vault is away."""
        try:
            return self.vault.root.is_dir() and self.vault.exists(SYSTEM)
        except VaultGone:
            return False

    def _forget_copy_mismatches(self, item_id: int) -> None:
        """A job that ran through starts the count again for the next time."""
        current = self.store.item(item_id)
        if current.overrides.get("copy_mismatches"):
            rest = {k: v for k, v in current.overrides.items() if k != "copy_mismatches"}
            self.store.update_item(item_id, overrides=rest)

    def _gone(self, item: Item) -> None:
        current = self.store.item(item.id)
        if current.state in BUSY:  # being filed or moved: `recover` finishes it
            log.warning("item %s is busy (%s), so it is not ended as gone", item.id, current.state)
            return
        self.pending_passwords.pop(item.id, None)
        self.store.update_item(item.id, state="gone")
        self.activity.record(
            item.id,
            Step.gone,
            "gone",
            "The file left the vault before it could be filed, so nothing was filed",
            file=item.rel_path,
        )

    def _copy_mismatch(self, kind: str, item: Item) -> None:
        """The first mismatch tries again; the second asks (ruling 17)."""
        current = self.store.item(item.id)
        if current.state in BUSY:
            return
        count = int(current.overrides.get("copy_mismatches", 0)) + 1
        if count == 1:
            with self.store.transaction():
                self.store.update_item(
                    item.id, overrides={**current.overrides, "copy_mismatches": count}
                )
                self.store.requeue(item.id, "refile" if kind == "refile" else "process")
            self.activity.record(
                item.id,
                Step.retried,
                "copy_mismatch",
                "The copy did not match the file, trying once more",
                file=current.rel_path,
            )
            return
        self.store.update_item(item.id, overrides={**current.overrides, "copy_mismatches": 0})
        self._ask(self.store.item(item.id), [Reason.copy_mismatch], None, {})

    def _failed(self, item: Item, exc: Exception) -> None:
        """Any other failure: the file goes to Needs a look, and the log names only the type."""
        current = self.store.item(item.id)
        if current.state in BUSY:  # being filed or filed already: never route it
            log.warning("a job found item %s busy: %s", item.id, type(exc).__name__)
            return
        log.warning("reading item %s failed: %s", item.id, type(exc).__name__)
        self.activity.record(
            item.id,
            Step.error,
            "read_failed",
            f"Could not read this file: {type(exc).__name__}",
            file=current.rel_path,
        )
        try:
            self._ask(current, [Reason.read_failed], None, {})
        except VaultGone:
            self._gone(current)

    def _give_up(self, item_id: int, exc: Exception) -> None:
        """Even the failure path failed: keep the file where it is and hold the item."""
        log.warning("job for item %s ended badly: %s", item_id, type(exc).__name__)
        try:
            self.pending_passwords.pop(item_id, None)
            if self.store.item(item_id).state not in BUSY:
                self.store.update_item(item_id, state="held")
                self.activity.record(
                    item_id, Step.error, "held", f"Held after an error: {type(exc).__name__}"
                )
        except Exception as inner:
            log.warning("could not hold item %s: %s", item_id, type(inner).__name__)

    # -- process and refile --------------------------------------------------------------------

    def _process(self, item: Item) -> None:
        rel = item.rel_path
        if rel is None:  # an upload stopped before it was filed: its photos were only in memory
            self._upload_again(item)
            return
        ov = overrides_of(item)
        self._step = "checking"
        result = check_file(
            self.vault, rel, self.store, self._seen, item_id=item.id, skip_duplicate=ov.keep_copy
        )
        self.activity.record(
            item.id, Step.checked, result.outcome, f"Checked: {result.outcome}", file=rel
        )
        self.store.update_item(
            item.id, sha256=result.sha256, kind=result.kind.value if result.kind else None
        )
        item = self.store.item(item.id)
        outcome = result.outcome
        if outcome == "locked" and item.id in self.pending_passwords:
            outcome = "ok"  # the owner gave the password; the reader opens it with that
        reason = _CHECK_REASONS.get(outcome)
        if reason is None and result.kind is FileKind.audio:
            reason = Reason.recording
        if reason is not None:
            self._ask_check(item, reason, result)
            return
        assert result.kind is not None
        self._step = "reading"
        source = DocumentSource(result.kind, data=self.vault.read_bytes(rel))
        held = None if "reread" in item.overrides else self.cards.held_reading(item.id, item.sha256)
        try:
            reading = held or read_document(
                source,
                result.sha256,
                self.engines,
                mode=self.settings.mode,
                password=self.pending_passwords.get(item.id),
                forced_type=ov.doc_type,
            )
        except LockedPdfError:
            self._ask(item, [Reason.locked], None, {})
            return
        except DamagedFileError:
            self._ask(item, [Reason.damaged], None, {"why": _WHY[Reason.damaged]})
            return
        label = LABEL[reading.doc_type] if reading.doc_type else "an unknown type"
        seconds = sum(reading.seconds.values())
        self.activity.record(
            item.id,
            Step.read,
            reading.doc_type.value if reading.doc_type else "no_type",
            f"Read as {label} in {seconds:.1f} s",
            file=rel,
        )
        if "reread" in item.overrides:
            rest = {k: v for k, v in item.overrides.items() if k != "reread"}
            self.store.update_item(item.id, overrides=rest)
            item = self.store.item(item.id)
        if (ov.doc_type or reading.doc_type) is DocType.card_front:
            self._step = "filing"
            try:
                outcome_of_card = self.cards.handle(item, reading, source, item.origin)
            except (ModelUnavailable, TargetGone, VaultGone, CopyMismatch):
                raise
            except Exception as exc:  # a card is never moved: it is asked about where it is
                self._card_failed(item, reading, exc)
                return
            if outcome_of_card == "waiting":
                self.store.update_item(item.id, state="waiting_secrets")
                self.activity.record(item.id, Step.waiting, "waiting", SECRETS_CLOSED, file=rel)
            return
        self._decide_and_file(item, reading, ov)

    def _upload_again(self, item: Item) -> None:
        question = upload_again_question()
        self.store.update_item(
            item.id,
            state="asked",
            reasons=[question.reason],
            question=dataclasses.asdict(question),
        )
        self.activity.record(item.id, Step.needs_a_look, "needs_a_look", question.text)

    def _card_failed(self, item: Item, reading: Reading, exc: Exception) -> None:
        """The card handler failed in a way nothing expects. The item is asked about in place:
        the photo is not moved to Needs a look, because it is not masked."""
        log.warning("filing a card for item %s failed: %s", item.id, type(exc).__name__)
        self.activity.record(
            item.id,
            Step.error,
            "read_failed",
            f"Could not file this card: {type(exc).__name__}",
            file=item.rel_path,
        )
        question = question_for([Reason.read_failed], reading, self.filer.household, {})
        self.store.update_item(
            item.id,
            state="asked",
            reasons=[Reason.read_failed],
            question=dataclasses.asdict(question),
            reading=stored_reading(reading, card_item=True),
        )
        self.activity.record(
            item.id, Step.needs_a_look, "needs_a_look", question.text, file=item.rel_path
        )

    def _refile(self, item: Item) -> None:
        """After an answer: decide again from the stored reading. A new type, a retry, a card
        (its number is never stored) or no stored reading means reading the file again first."""
        ov = overrides_of(item)
        reading = Reading.model_validate(item.reading) if item.reading else None
        stored_type = reading.doc_type if reading else None
        again = (
            reading is None
            or bool(item.overrides.get("reread"))
            or (ov.doc_type is not None and ov.doc_type != stored_type)
            or (ov.doc_type or stored_type) is DocType.card_front
        )
        if again or reading is None:
            self._process(item)
            return
        self._decide_and_file(item, reading, ov)

    def _decide_and_file(self, item: Item, reading: Reading, ov: Overrides) -> None:
        item = self.store.item(item.id)
        doc_type = ov.doc_type or reading.doc_type
        filed = self.store.documents_of_type(doc_type) if doc_type else []
        decision = decide(reading, self.filer.household, self.clock().date(), filed, ov)
        if decision.outcome == "file":
            self._step = "filing"
            self.filer.file(item, reading, decision)
            return
        context: dict[str, str] = {}
        if decision.printed_names:
            context["printed"] = next(iter(decision.printed_names.values()))
        if decision.possible_copy_of:
            other = self.store.document(decision.possible_copy_of)
            if other is not None:
                context["path"] = other.rel_path
                context["date"] = other.created_at.date().isoformat()
                # Kept so a discard can check that this document is still there.
                self.store.update_item(item.id, overrides={**item.overrides, "copy_of": other.id})
        self._ask(item, decision.reasons, reading, context, effective_reading(reading, ov))

    # -- asking --------------------------------------------------------------------------------

    def _ask_check(self, item: Item, reason: Reason, result: CheckResult) -> None:
        context: dict[str, str] = {}
        if result.duplicate_of:
            context["path"] = result.duplicate_of
        if reason in _WHY:
            context["why"] = _WHY[reason]
        if reason is Reason.duplicate and any(
            is_card_item(other)
            for other in self.store.items_with_sha(item.sha256, CARD_STATES)
            if other.id != item.id
        ):
            self._ask_in_place(item, reason, context)  # the original is a card: never moved
            return
        self._ask(item, [reason], None, context)

    def _ask_in_place(self, item: Item, reason: Reason, context: dict[str, str]) -> None:
        question = question_for([reason], None, self.filer.household, context)
        with self.filer.lock:
            self.store.update_item(
                item.id,
                state="asked",
                reasons=[reason],
                question=dataclasses.asdict(question),
            )
            self.activity.record(
                item.id, Step.needs_a_look, "needs_a_look", question.text, file=item.rel_path
            )

    def _ask(
        self,
        item: Item,
        reasons: list[Reason],
        stored: Reading | None,
        context: dict[str, str],
        shown: Reading | None = None,
    ) -> None:
        question: Question = question_for(reasons, shown or stored, self.filer.household, context)
        if item.rel_path is not None and self._seen.get(item.sha256) == item.rel_path:
            del self._seen[item.sha256]  # the file is leaving this path; it is not "seen" there
        self.filer.to_needs_a_look(item, reasons, question, stored)
