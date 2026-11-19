"""The card flows, end to end over the synthetic cards of eval-v1: a photo dropped in Inbox, a
photo uploaded in the app, and what each leaves in the vault, the database and the logs."""

import io
import logging
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image
from vault_synth.cli import generate
from vault_synth.model import SynthDoc
from vault_synth.sets import SETS, locked_password

from household_vault.actions import AnswerError
from household_vault.db import Item
from household_vault.doctypes import DocType
from household_vault.filing.filer import UndoError
from household_vault.filing.records import read_record
from household_vault.leakscan import install_log_redaction, scan_outputs
from household_vault.reading.engines import Engines
from household_vault.reading.lines import Line, PageText
from household_vault.reasons import Reason
from household_vault.secrets.cards import TRASH_NOTE, CardIntake, CardUploadError
from household_vault.secrets.gate import SecretsGate
from household_vault.secrets.store import SecretsLocked, SecretsStore
from household_vault.vaultroot import INBOX, NEEDS_A_LOOK, SECRETS_FILE, VaultRoot
from tests.conftest import MASTER_PASSWORD, FakeClock, World, _eval_docs, drop
from tests.fakes import EVAL_V1, TruthModels, TruthPages


def vault_files(vault: VaultRoot) -> list[str]:
    found: list[str] = []
    todo = [""]
    while todo:
        folder = todo.pop()
        for entry in vault.list_dir(folder) if folder else vault.list_root():
            rel = f"{folder}/{entry.name}" if folder else entry.name
            if entry.kind == "dir":
                todo.append(rel)
            else:
                found.append(rel)
    return sorted(found)


def forbid_temp_files(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any use of the tempfile module fails the test: a photo upload must stay in memory."""

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("an upload must not use a temporary file")

    for name in (
        "mkstemp",
        "mkdtemp",
        "NamedTemporaryFile",
        "TemporaryFile",
        "TemporaryDirectory",
        "SpooledTemporaryFile",
    ):
        monkeypatch.setattr(tempfile, name, refuse)


class ReadsMaskedAs(TruthPages):
    """The truth pages for the original photos; the masked copy (not in the set) reads as the
    given lines."""

    def __init__(self, docs: Any, folder: Path, masked_lines: list[str]) -> None:
        super().__init__(docs, folder)
        self.masked_lines = masked_lines
        self.masked_reads = 0

    def read_pages(self, source: Any, sha256: str, password: str | None) -> Any:
        try:
            return super().read_pages(source, sha256, password)
        except ValueError:
            self.masked_reads += 1
            lines = [
                Line(text=t, bbox=(0.1, 0.1 + 0.1 * i, 0.9, 0.18 + 0.1 * i))
                for i, t in enumerate(self.masked_lines)
            ]
            return [PageText(page=0, width=1000, height=700, lines=lines)]


@dataclass
class Card:
    doc: SynthDoc
    files: list[bytes]

    @property
    def data(self) -> bytes:
        return self.files[0]

    @property
    def number(self) -> str:
        number = self.doc.fields["number"]
        assert isinstance(number, str)
        return number


@dataclass
class CardWorld:
    world: World
    settings: Any
    gate: SecretsGate
    gate_clock: FakeClock
    cards: CardIntake
    models: TruthModels
    docs: list[SynthDoc]
    folder: Path
    locked: list[SynthDoc]
    _locked_used: int = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self.world, name)

    def drain(self) -> None:
        self.world.drain()

    def secrets(self) -> SecretsStore:
        return self.gate.store()

    def card(self, base: int) -> Card:
        doc = next(d for d in self.docs if d.doc_id == f"card_front-{base}-photo")
        return Card(doc, [(self.folder / name).read_bytes() for name in doc.files])

    def drop_card(self, base: int, name: str = "card.jpg") -> Card:
        card = self.card(base)
        drop(self.vault, name, card.data)
        return card

    def locked_item(self) -> Any:
        """A different locked policy each call, dropped in Inbox and asked for its password."""
        doc = self.locked[self._locked_used]
        self._locked_used += 1
        drop(
            self.vault, f"policy-{self._locked_used}.pdf", (self.folder / doc.files[0]).read_bytes()
        )
        self.drain()
        item = next(
            i
            for i in self.store.items(["asked"])
            if i.reasons == [Reason.locked] and i.original_name.endswith(f"{self._locked_used}.pdf")
        )
        return SimpleNamespace(id=item.id, password=doc.password)


@pytest.fixture(scope="session")
def empty_secrets_file(tmp_path_factory: pytest.TempPathFactory) -> bytes:
    """One new secrets file, made once: creating a KeePass file takes about a second."""
    root = tmp_path_factory.mktemp("kdbx") / "vault"
    vault = VaultRoot(root, mode="dev")
    vault.mkdirs("Inbox")
    SecretsStore.create(vault, MASTER_PASSWORD)
    return vault.read_bytes(SECRETS_FILE)


@pytest.fixture(scope="session")
def card_set(tmp_path_factory: pytest.TempPathFactory) -> tuple[list[SynthDoc], Path]:
    """The test-split cards of eval-v1 (bases 5 and 10), with every one filing without a
    question, and a few locked policies copied in beside them."""
    out = tmp_path_factory.mktemp("cards")
    spec = replace(
        SETS["eval-v1"], outsider_rate=0.0, ambiguous_rate=0.0, missing_required_rate=0.0
    )
    docs = generate("eval-v1", out, splits=("test",), types=[DocType.card_front], spec=spec)
    locked = [d for d in _eval_docs() if d.variant == "locked" and not d.expected_ask][:4]
    for doc in locked:
        shutil.copy(EVAL_V1 / doc.files[0], out / doc.files[0])
    return [*docs, *locked], out


@pytest.fixture
def card_world(
    make_world: Callable[..., World],
    settings: Any,
    card_set: tuple[list[SynthDoc], Path],
    empty_secrets_file: bytes,
) -> CardWorld:
    docs, folder = card_set
    models = TruthModels(docs, folder)
    world = make_world(pages=ReadsMaskedAs(docs, folder, []), models=models)
    world.vault.write_atomic(SECRETS_FILE, empty_secrets_file)
    (settings.log_dir / "vault.log").write_text("app started\n")  # the scan reads a real log
    gate_clock = FakeClock(0.0)
    gate = SecretsGate(world.vault, gate_clock)
    gate.unlock(MASTER_PASSWORD)
    engines = Engines(world.worker.engines.pages, models)
    cards = CardIntake(
        gate, world.vault, world.filer, world.activity, world.store, engines, world.filer.household
    )
    world.worker.cards = cards
    world.actions.gate = gate
    locked = [
        d.model_copy(update={"password": locked_password(d.base_id)})
        for d in docs
        if d.variant == "locked"
    ]
    return CardWorld(world, settings, gate, gate_clock, cards, models, docs, folder, locked)


def _bytes_everywhere(world: CardWorld) -> bytes:
    out = []
    for rel in vault_files(world.vault):
        if rel != SECRETS_FILE:
            out.append(world.vault.read_bytes(rel))
    for root in (world.db_dir,):
        out.extend(p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file())
    return b"\n".join(out)


# -- from Inbox ---------------------------------------------------------------------------------


def test_card_secrets_live_only_in_the_store(card_world):
    card = card_world.drop_card(base=5)  # front only
    card_world.drain()
    (doc,) = card_world.store.documents_of_type(DocType.card_front)
    assert (doc.fields["number"], doc.fields["cvv"], doc.fields["last4"]) == (
        None,
        None,
        card.number[-4:],
    )
    assert doc.rel_path.startswith(card.doc.folder + "/")
    assert card_world.secrets().entry_fields(doc.secret_ref)["number"] == card.number
    assert (
        scan_outputs(
            card_world.vault,
            card_world.settings.db_path,
            card_world.settings.log_dir,
            known_secrets=[card.number, MASTER_PASSWORD],
        )
        == []
    )
    others = [p for p in vault_files(card_world.vault) if p != SECRETS_FILE]
    assert all(card_world.vault.read_bytes(p) != card.data for p in others)
    everything = _bytes_everywhere(card_world)
    assert card.number.encode() not in everything
    assert MASTER_PASSWORD.encode() not in everything


def test_the_filed_copy_is_masked_down_to_the_last_four(card_world):
    card = card_world.drop_card(base=5)
    card_world.drain()
    (doc,) = card_world.store.documents_of_type(DocType.card_front)
    assert doc.rel_path.endswith(".jpg")
    filed = Image.open(io.BytesIO(card_world.vault.read_bytes(doc.rel_path))).convert("L")
    grouped = next(ln for ln in card.doc.lines if card.number[:4] in ln.text.replace(" ", ""))
    x0, y0, x1, y1 = grouped.bbox
    w, h = filed.size
    covered = filed.crop(
        (int(x0 * w) + 2, int(y0 * h) + 2, int((x0 + (x1 - x0) * 0.5) * w), int(y1 * h) - 2)
    )
    assert max(covered.get_flattened_data()) < 40
    assert doc.fields["last4"] == card.number[-4:]


def test_a_card_from_the_inbox_waits_while_the_store_is_locked(card_world):
    card_world.gate.lock()
    card = card_world.drop_card(base=5)
    card_world.drain()
    assert card_world.vault.read_bytes("Inbox/card.jpg") == card.data
    assert not card_world.store.documents_of_type(DocType.card_front)
    card_world.gate.unlock(MASTER_PASSWORD)
    card_world.drain()
    assert not card_world.vault.exists("Inbox/card.jpg")
    assert TRASH_NOTE in [e.detail for e in card_world.activity.entries()]


def test_a_waiting_card_is_read_by_the_models_once(card_world):
    card_world.gate.lock()
    card_world.drop_card(base=5)
    card_world.drain()
    card_world.drain()
    after_first = card_world.models.calls
    assert after_first == 2  # the type and the fields, once
    card_world.gate.unlock(MASTER_PASSWORD)
    card_world.drain()
    assert card_world.models.calls == after_first
    assert card_world.store.documents_of_type(DocType.card_front)
    assert card_world.cards._held == {}


def test_a_gate_that_runs_out_again_keeps_the_card_waiting(card_world):
    card_world.drop_card(base=5)
    card_world.gate_clock.t = 1000.0  # past the ten minutes
    card_world.drain()
    (item,) = card_world.store.items(["waiting_secrets"])
    assert card_world.vault.exists(item.rel_path)
    card_world.gate.unlock(MASTER_PASSWORD)
    card_world.drain()
    assert card_world.store.documents_of_type(DocType.card_front)


def test_the_master_password_and_numbers_are_redacted_from_every_log_line(card_world, caplog):
    install_log_redaction(card_world.gate.held_secrets)
    caplog.set_level(logging.INFO)
    logging.getLogger("household_vault.anything").info("number %s", "4111111111111111")
    logging.getLogger("household_vault.anything").info("pw %s", MASTER_PASSWORD)
    assert "4111111111111111" not in caplog.text and "XXXXXXXXXXXX1111" in caplog.text
    assert MASTER_PASSWORD not in caplog.text


def test_the_logs_and_the_activity_never_hold_a_secret(card_world, caplog):
    caplog.set_level(logging.DEBUG)
    card = card_world.drop_card(base=5)
    card_world.drain()
    entries = " ".join(e.detail + (e.file or "") for e in card_world.activity.entries(500))
    for secret in (card.number, MASTER_PASSWORD):
        assert secret not in caplog.text and secret not in entries


def test_a_card_back_with_a_cvv_and_no_number_asks_for_both_sides(card_world):
    card_world.models.patch = {"number": None, "cvv": "123"}
    card_world.drop_card(base=5)
    card_world.drain()
    (item,) = card_world.store.items(["asked"])
    assert item.reasons == [Reason.card_unreadable]
    assert item.question and "back of a card" in item.question["text"]
    assert "123" not in str(item.reading)


def test_a_number_that_fails_the_check_asks_in_place_and_stores_nothing(card_world):
    card_world.models.patch = {"number": "4111111111111112"}
    card = card_world.drop_card(base=5)
    card_world.drain()
    (item,) = card_world.store.items(["asked"])
    assert item.reasons == [Reason.card_unreadable]
    assert item.rel_path == "Inbox/card.jpg"
    assert card_world.vault.read_bytes("Inbox/card.jpg") == card.data
    assert card_world.vault.list_dir(NEEDS_A_LOOK) == []
    assert card_world.secrets().entries("Cards") == []
    lines = [ln["text"] for p in item.reading["pages"] for ln in p["lines"]]
    assert not any(card.number[:-4] in t.replace(" ", "") for t in lines)


def test_a_card_without_a_known_person_asks_in_place_then_files(card_world):
    card_world.models.patch = {"holder": "Zed Nobody"}
    card = card_world.drop_card(base=5)
    card_world.drain()
    (item,) = card_world.store.items(["asked"])
    assert item.reasons == [Reason.person_unknown] and item.rel_path == "Inbox/card.jpg"
    assert card_world.vault.list_dir(NEEDS_A_LOOK) == []
    card_world.actions.answer(item.id, "person", "p2")
    card_world.drain()
    (doc,) = card_world.store.documents_of_type(DocType.card_front)
    assert doc.owner == "p2" and doc.rel_path.startswith("Kavita Rao/Cards/")
    assert card_world.secrets().entry_fields(doc.secret_ref)["number"] == card.number


def test_the_same_card_dropped_again_is_found_by_bank_and_last_four(card_world):
    card_world.drop_card(base=5)
    card_world.drain()
    card_world.drop_card(base=5, name="again.jpg")
    card_world.drain()
    (item,) = card_world.store.items(["asked"])
    assert item.reasons == [Reason.possible_copy]
    assert len(card_world.secrets().entries("Cards")) == 1
    assert card_world.vault.exists("Inbox/again.jpg")


def test_a_filing_that_is_read_again_does_not_make_a_second_entry(card_world, monkeypatch):
    real = card_world.filer.file_new
    calls = []

    def flaky(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        if len(calls) == 1:
            raise OSError("disk full")
        return real(*args, **kwargs)

    monkeypatch.setattr(card_world.filer, "file_new", flaky)
    card_world.drop_card(base=5)
    card_world.drain()
    (item,) = card_world.store.items(["asked"])
    assert item.reasons == [Reason.read_failed] and item.rel_path == "Inbox/card.jpg"
    assert card_world.vault.list_dir(NEEDS_A_LOOK) == []
    assert len(card_world.secrets().entries("Cards")) == 1
    card_world.actions.retry(item.id)
    card_world.drain()
    assert card_world.store.documents_of_type(DocType.card_front)
    assert len(card_world.secrets().entries("Cards")) == 1


def test_a_card_pdf_in_needs_a_look_reaches_the_handler(card_world):
    """A type answer of card on a PDF in Needs a look: the handler files it from there."""
    doc = next(d for d in card_world.docs if d.doc_id == "card_front-5-clean")
    data = (card_world.folder / doc.files[0]).read_bytes()
    card_world.vault.write_atomic(f"{NEEDS_A_LOOK}/card.pdf", data)
    import hashlib

    item = card_world.store.add_item(
        hashlib.sha256(data).hexdigest(), "card.pdf", f"{NEEDS_A_LOOK}/card.pdf", card_world.clock()
    )
    card_world.store.update_item(item.id, state="asked", kind="pdf")
    card_world.actions.answer(item.id, "type", "card_front")
    card_world.drain()
    (rec,) = card_world.store.documents_of_type(DocType.card_front)
    assert rec.rel_path.startswith("Ravi Kumar Rao/Cards/")
    assert not card_world.vault.exists(f"{NEEDS_A_LOOK}/card.pdf")
    assert card_world.secrets().entry_fields(rec.secret_ref)["number"] == doc.fields["number"]
    names = card_world.secrets().attachment_names(rec.secret_ref)
    assert names == ["front.pdf"]


# -- from the app ---------------------------------------------------------------------------------


def test_an_upload_files_without_writing_the_photo(card_world, monkeypatch):  # ruling 19
    forbid_temp_files(monkeypatch)
    card = card_world.card(base=10)  # front and back
    rec = card_world.cards.upload(card.files, MASTER_PASSWORD)
    assert (
        rec.rel_path.startswith(card.doc.folder + "/") and card_world.vault.list_dir("Inbox") == []
    )
    item = card_world.store.item(card_world.store.document(rec.id).item_id)
    assert (item.origin, item.rel_path, item.state, item.document_id) == (
        "upload",
        None,
        "filed",
        rec.id,
    )
    assert card_world.secrets().entry_fields(rec.secret_ref)["cvv"] == card.doc.fields["cvv"]
    assert len(card_world.secrets().attachment_names(rec.secret_ref)) == 2


def test_an_upload_keeps_the_cvv_out_of_every_record(card_world):
    card = card_world.card(base=10)
    rec = card_world.cards.upload(card.files, MASTER_PASSWORD)
    cvv = card.doc.fields["cvv"]
    stored = read_record(card_world.vault, rec.id)
    texts = [ln.text for page in stored.pages for ln in page.lines]
    assert cvv not in texts and rec.fields["cvv"] is None
    item = card_world.store.item(rec.item_id)
    assert cvv not in [ln["text"] for p in item.reading["pages"] for ln in p["lines"]]
    assert (
        scan_outputs(
            card_world.vault,
            card_world.settings.db_path,
            card_world.settings.log_dir,
            known_secrets=[card.number],
        )
        == []
    )


def test_an_upload_with_the_wrong_master_password_does_nothing(card_world):
    card_world.gate.lock()
    card = card_world.card(base=5)
    with pytest.raises(SecretsLocked):
        card_world.cards.upload(card.files, "wrong")
    assert card_world.store.items(["queued", "reading", "asked", "filed"]) == []
    assert not card_world.gate.is_open()


def test_an_upload_that_cannot_be_read_ends_asked_with_nothing_written(card_world):
    card_world.models.patch = {"number": None}
    card = card_world.card(base=5)
    result = card_world.cards.upload(card.files, MASTER_PASSWORD)
    assert isinstance(result, Item) and result.state == "asked"
    assert result.reasons == [Reason.card_unreadable] and result.rel_path is None
    assert card_world.vault.list_dir(INBOX) == []
    assert card_world.secrets().entries("Cards") == []
    assert not card_world.store.documents_of_type(DocType.card_front)


def test_an_upload_must_be_one_or_two_pictures(card_world):
    card = card_world.card(base=5)
    for files in ([], [card.data] * 3, [b"%PDF-1.4 not a picture"]):
        with pytest.raises(CardUploadError):
            card_world.cards.upload(files, MASTER_PASSWORD)


def test_an_upload_with_no_vault_file_cannot_be_read_again(card_world):
    item = card_world.store.add_item(
        "a" * 64, "card upload", None, card_world.clock(), origin="upload"
    )
    card_world.store.enqueue(item.id, "process")
    card_world.drain()
    stopped = card_world.store.item(item.id)
    assert stopped.state == "asked"
    assert "Upload it again" in stopped.question["text"]


# -- passwords and Undo --------------------------------------------------------------------------


def test_a_pdf_password_is_saved_only_when_asked(card_world):
    for save in (False, True):
        item = card_world.locked_item()
        card_world.actions.unlock(
            item.id, item.password, save=save, master_password=MASTER_PASSWORD
        )
        card_world.drain()
    assert len(card_world.secrets().entries("Documents")) == 1


def test_saving_a_password_needs_the_right_master_password(card_world):
    item = card_world.locked_item()
    with pytest.raises(AnswerError, match="master password"):
        card_world.actions.unlock(item.id, item.password, save=True, master_password="wrong")
    with pytest.raises(AnswerError, match="Enter the master password"):
        card_world.actions.unlock(item.id, item.password, save=True)
    assert card_world.secrets().entries("Documents") == []
    assert card_world.store.item(item.id).state == "asked"


def test_a_wrong_pdf_password_is_never_saved(card_world):
    item = card_world.locked_item()
    with pytest.raises(AnswerError, match="did not open"):
        card_world.actions.unlock(item.id, "wrong", save=True, master_password=MASTER_PASSWORD)
    assert card_world.secrets().entries("Documents") == []


def test_undo_puts_the_original_photo_back_and_keeps_the_entry(card_world):
    card = card_world.drop_card(base=5)
    card_world.drain()
    (doc,) = card_world.store.documents_of_type(DocType.card_front)
    held = card_world.actions.undo_document(doc.id)
    assert held.state == "held" and held.rel_path is not None
    assert card_world.vault.read_bytes(held.rel_path) == card.data
    assert not card_world.vault.exists(doc.rel_path)
    assert not card_world.store.documents_of_type(DocType.card_front)
    assert held.overrides["secret_ref"] == doc.secret_ref
    assert len(card_world.secrets().entries("Cards")) == 1
    card_world.actions.retry(held.id)
    card_world.drain()
    (again,) = card_world.store.documents_of_type(DocType.card_front)
    assert again.secret_ref == doc.secret_ref
    assert len(card_world.secrets().entries("Cards")) == 1


def test_undo_of_a_card_needs_the_store_open_and_changes_nothing_otherwise(card_world):
    card_world.drop_card(base=5)
    card_world.drain()
    (doc,) = card_world.store.documents_of_type(DocType.card_front)
    card_world.gate.lock()
    with pytest.raises(UndoError, match="Unlock the secrets store"):
        card_world.actions.undo_document(doc.id)
    assert card_world.vault.exists(doc.rel_path)
    assert card_world.store.document(doc.id) is not None


def test_a_card_undo_that_was_stopped_is_finished_or_rolled_back(card_world, monkeypatch):
    card = card_world.drop_card(base=5)
    card_world.drain()
    (doc,) = card_world.store.documents_of_type(DocType.card_front)

    def stop(item_id: int) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(card_world.filer, "_finish_move", stop)
    with pytest.raises(KeyboardInterrupt):
        card_world.actions.undo_document(doc.id)
    monkeypatch.undo()
    (stuck,) = card_world.store.items(["undoing"])
    assert card_world.vault.read_bytes(stuck.rel_path) == card.data
    card_world.filer.recover()
    held = card_world.store.item(stuck.id)
    assert held.state == "held" and not card_world.vault.exists(doc.rel_path)
    assert card_world.store.document(doc.id) is None


def test_a_card_undo_stopped_before_the_photo_was_written_stays_filed(card_world, monkeypatch):
    card_world.drop_card(base=5)
    card_world.drain()
    (doc,) = card_world.store.documents_of_type(DocType.card_front)

    def stop(*args: Any) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(card_world.filer, "_write_bytes", stop)
    with pytest.raises(KeyboardInterrupt):
        card_world.actions.undo_document(doc.id)
    monkeypatch.undo()
    card_world.filer.recover()
    item = card_world.store.item(doc.item_id)
    assert item.state == "filed" and card_world.vault.exists(doc.rel_path)
    assert card_world.store.document(doc.id) is not None


def test_undo_of_an_uploaded_card_is_refused_and_writes_no_photo(card_world):
    rec = card_world.cards.upload(card_world.card(base=10).files, MASTER_PASSWORD)
    with pytest.raises(UndoError, match="came from an upload"):
        card_world.actions.undo_document(rec.id)
    assert card_world.vault.list_dir(INBOX) == []
    assert card_world.store.document(rec.id) is not None
    assert card_world.vault.exists(rec.rel_path)
    assert card_world.secrets().has_entry(rec.secret_ref)
    card_world.gate.lock()
    with pytest.raises(UndoError, match="came from an upload"):
        card_world.actions.undo_document(rec.id)


def test_a_stop_right_after_the_entry_is_saved_leaves_one_entry(card_world, monkeypatch):
    store = card_world.secrets()
    real = store.add_card

    def stop_after_saving(*args: Any, **kwargs: Any) -> str:
        real(*args, **kwargs)
        raise KeyboardInterrupt  # the process stops once the entry is on disk

    monkeypatch.setattr(store, "add_card", stop_after_saving)
    card_world.drop_card(base=5)
    with pytest.raises(KeyboardInterrupt):
        card_world.drain()
    monkeypatch.undo()
    (item,) = card_world.store.items(["reading"])
    assert "secret_ref" in item.overrides  # saved before the entry was made
    with card_world.store.lock:  # a hard stop leaves the job marked running
        card_world.store.conn.execute("update jobs set state = 'running'")
    fresh = CardIntake(
        card_world.gate,
        card_world.vault,
        card_world.filer,
        card_world.activity,
        card_world.store,
        card_world.cards.engines,
        card_world.filer.household,
    )
    card_world.world.worker.cards = fresh
    card_world.world.worker.start_up()
    card_world.drain()
    assert card_world.store.documents_of_type(DocType.card_front)
    assert len(card_world.secrets().entries("Cards")) == 1


def test_a_heic_upload_is_refused_without_a_temporary_file(card_world, monkeypatch):
    forbid_temp_files(monkeypatch)
    heic = b"\x00\x00\x00\x18ftypheic" + b"\x00" * 64
    with pytest.raises(CardUploadError, match="Upload a JPEG or PNG photo"):
        card_world.cards.upload([heic], MASTER_PASSWORD)
    assert card_world.store.items(["queued", "reading", "asked", "filed"]) == []


def test_an_upload_that_is_asked_to_be_sent_again_forgets_its_held_reading(card_world):
    item = card_world.store.add_item(
        "b" * 64, "card upload", None, card_world.clock(), origin="upload"
    )
    card_world.cards._held[item.id] = (item.sha256, object())  # type: ignore[assignment]
    card_world.cards._upload_again(item.id)
    assert card_world.cards._held == {}


# -- the masked copy is read again before it is filed ------------------------------------------


def _reads_masked_as(card_world: CardWorld, lines: list[str]) -> ReadsMaskedAs:
    pages = ReadsMaskedAs(card_world.docs, card_world.folder, lines)
    card_world.cards.engines = Engines(pages, card_world.models)
    return pages


def test_a_masked_copy_that_still_reads_as_the_number_is_never_filed(card_world):
    _reads_masked_as(card_world, ["3782 82"])
    card = card_world.drop_card(base=5)
    card_world.drain()
    (item,) = card_world.store.items(["asked"])
    assert item.reasons == [Reason.card_unreadable]
    assert item.question["text"] == "Take a straighter photo of the card."
    assert card_world.vault.read_bytes("Inbox/card.jpg") == card.data
    assert [
        p
        for p in vault_files(card_world.vault)
        if p not in (SECRETS_FILE, "Inbox/card.jpg") and not p.startswith("_system/")
    ] == []
    assert not card_world.store.documents_of_type(DocType.card_front)
    assert card_world.secrets().entries("Cards") == []
    assert card_world.vault.list_dir(NEEDS_A_LOOK) == []


def test_an_expiry_read_on_the_masked_copy_does_not_stop_the_filing(card_world):
    pages = _reads_masked_as(card_world, ["05/29", "TEST BANK", "1111"])
    card_world.drop_card(base=5)
    card_world.drain()
    assert pages.masked_reads == 1
    assert card_world.store.documents_of_type(DocType.card_front)


def test_an_upload_whose_masked_copy_still_shows_the_number_writes_nothing(card_world):
    _reads_masked_as(card_world, ["3782 822"])
    result = card_world.cards.upload(card_world.card(base=5).files, MASTER_PASSWORD)
    assert isinstance(result, Item) and result.state == "asked"
    assert result.question["text"] == "Take a straighter photo of the card."
    assert card_world.secrets().entries("Cards") == [] and card_world.vault.list_dir(INBOX) == []


def test_a_reader_that_is_down_on_the_second_read_defers_the_card(card_world):
    from household_vault.reading.ollama import ModelUnavailable

    class Down(ReadsMaskedAs):
        def read_pages(self, source: Any, sha256: str, password: str | None) -> Any:
            try:
                return TruthPages.read_pages(self, source, sha256, password)
            except ValueError:
                raise ModelUnavailable("the reader is down") from None

    card_world.cards.engines = Engines(
        Down(card_world.docs, card_world.folder, []), card_world.models
    )
    card = card_world.drop_card(base=5)
    card_world.drain()
    assert card_world.store.items(["asked", "filed"]) == []
    (item,) = card_world.store.items(["queued"])
    assert card_world.vault.read_bytes("Inbox/card.jpg") == card.data
    assert [p for p in vault_files(card_world.vault) if p.startswith("Ravi")] == []
    assert card_world.secrets().entries("Cards") == []
    assert not card_world.store.documents_of_type(DocType.card_front)
    assert item.state == "queued"


def test_a_gate_that_closes_while_the_card_is_filed_leaves_it_waiting(card_world, monkeypatch):
    real = card_world.gate.store
    calls = []

    def store_then_locked() -> Any:
        calls.append(1)
        if len(calls) > 1:
            raise SecretsLocked("the secrets store is locked")
        return real()

    monkeypatch.setattr(card_world.gate, "store", store_then_locked)
    card = card_world.drop_card(base=5)
    card_world.drain()
    (item,) = card_world.store.items(["waiting_secrets"])
    assert card_world.vault.read_bytes("Inbox/card.jpg") == card.data
    assert not card_world.store.documents_of_type(DocType.card_front)
    monkeypatch.undo()
    card_world.drain()
    assert card_world.store.documents_of_type(DocType.card_front)
    assert card_world.store.item(item.id).state == "filed"


def test_a_heic_card_is_converted_once_for_the_whole_card(card_world, monkeypatch):
    """`sips` writes the unmasked photo to a temporary folder on each conversion, so the reader,
    the mask and the image checks share one."""
    import hashlib

    from household_vault.intake.sniff import FileKind
    from household_vault.reading import engines, pipeline
    from household_vault.reading.pipeline import read_document
    from household_vault.reading.source import DocumentSource

    card = card_world.card(5)
    sha = hashlib.sha256(card.data).hexdigest()
    calls: list[int] = []

    def convert(data: bytes) -> bytes:
        calls.append(1)
        return data  # the stand-in: the bytes are already an image

    monkeypatch.setattr(engines, "heic_to_png", convert)
    monkeypatch.setattr(pipeline, "heic_to_png", convert)
    source = DocumentSource(FileKind.heic, data=card.data)
    reading = read_document(
        source, sha, card_world.cards.engines, mode="dev", forced_type=DocType.card_front
    )
    item = card_world.store.add_item(sha, "card.heic", None, card_world.filer.clock())
    outcome = card_world.cards.handle(item, reading, source, "inbox")
    assert outcome == "filed"
    assert len(calls) == 1
