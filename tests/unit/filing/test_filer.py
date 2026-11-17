import hashlib
from datetime import date
from typing import Any

import pytest
from vault_synth.household import HOUSEHOLD

from household_vault.activity import Activity, Step
from household_vault.db import Item, Store
from household_vault.doctypes import Area, DocType
from household_vault.filing import records
from household_vault.filing.decide import Decision
from household_vault.filing.filer import Filer, UndoError
from household_vault.filing.questions import Option, Question
from household_vault.filing.records import decision_to_json, read_record
from household_vault.reasons import Reason
from household_vault.vaultroot import INBOX, NEEDS_A_LOOK, CopyMismatch, VaultRoot
from tests.conftest import raise_
from tests.unit.filing.samples import (
    DECISION,
    NOW,
    READING,
    card_reading,
)

FOLDER = "Ravi Kumar Rao/Insurance"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def count_files(vault: VaultRoot, folder: str) -> int:
    """Every file under folder, hidden ones too, so a leftover partial copy shows."""
    total = 0
    for entry in vault.list_dir(folder):
        if entry.kind == "dir":
            total += count_files(vault, f"{folder}/{entry.name}")
        else:
            total += 1
    return total


def make_item(vault: VaultRoot, store: Store, name: str, data: bytes, kind: str = "pdf") -> Item:
    vault.write_atomic(f"{INBOX}/{name}", data)
    item = store.add_item(sha(data), name, f"{INBOX}/{name}", NOW)
    return store.update_item(item.id, kind=kind, state="reading")


@pytest.fixture
def filer(vault, store, activity, clock) -> Filer:
    return Filer(vault, store, activity, HOUSEHOLD, clock)


def fresh_filer(vault: VaultRoot, store: Store) -> Filer:
    """A second Filer on the same files and database, as after a restart."""
    return Filer(vault, store, Activity(store, vault, lambda: NOW), HOUSEHOLD, lambda: NOW)


@pytest.fixture
def inbox_item(vault, store) -> Item:
    return make_item(vault, store, "policy.pdf", b"%PDF-1.4 first policy")


@pytest.fixture
def clash_item(vault, store) -> Item:
    return make_item(vault, store, "policy copy.pdf", b"%PDF-1.4 second policy")


CARD_DECISION = Decision(
    outcome="file",
    reasons=[],
    owner="p1",
    linked=["p1"],
    area=Area.cards,
    folder="Ravi Kumar Rao/Cards",
    doc_date=date(2026, 11, 20),
    date_source="received",
    description="Card - HDFC Bank ending 1111",
    possible_copy_of=None,
    printed_names={},
    last4="1111",
)


def test_file_copies_verifies_records_and_clears_the_inbox(
    filer, vault, store, inbox_item, clash_item
):
    rec = filer.file(inbox_item, READING, DECISION)
    assert rec.rel_path == "Ravi Kumar Rao/Insurance/2026-04-01 Health policy - Star Health.pdf"
    assert vault.sha256(rec.rel_path) == inbox_item.sha256 and not vault.exists(inbox_item.rel_path)
    assert read_record(vault, rec.id) == rec and store.document(rec.id).rel_path == rec.rel_path
    second = filer.file(clash_item, READING, DECISION)
    assert second.rel_path.endswith("Star Health (2).pdf")
    done = store.item(inbox_item.id)
    assert (done.state, done.document_id, done.target, done.pending) == (
        "filed",
        rec.id,
        None,
        None,
    )
    assert store.people_of(rec.id) == [("p1", "owner"), ("p3", "linked")]
    assert store.conn.execute("select count(*) from lines").fetchone()[0] == 2
    assert filer.activity.entries()[0].step is Step.filed
    assert filer.activity.entries()[0].file == second.rel_path


def test_a_failed_copy_leaves_the_original(filer, vault, store, inbox_item, monkeypatch):
    before = vault.read_bytes(inbox_item.rel_path)
    monkeypatch.setattr(vault, "copy_verified", raise_(CopyMismatch("copy does not match")))
    with pytest.raises(CopyMismatch):
        filer.file(inbox_item, READING, DECISION)
    assert vault.read_bytes(inbox_item.rel_path) == before and not store.documents_of_type(
        DocType.health_policy
    )
    item = store.item(inbox_item.id)
    assert (item.target, item.pending) == (None, None) and item.state == "reading"


def test_a_real_mismatch_leaves_no_partial_and_no_record(filer, vault, store, inbox_item):
    bad = store.update_item(inbox_item.id, sha256="0" * 64)  # the file is not what was hashed
    with pytest.raises(CopyMismatch):
        filer.file(bad, READING, DECISION)
    assert vault.exists(inbox_item.rel_path) and count_files(vault, "Ravi Kumar Rao") == 0
    assert not vault.exists("_system/records")


def test_restart_after_stop_between_copy_and_clear(  # Review Focus 7
    filer, vault, store, inbox_item, monkeypatch
):
    with monkeypatch.context() as mp:
        mp.setattr(vault, "unlink", raise_(KeyboardInterrupt()))
        with pytest.raises(KeyboardInterrupt):
            filer.file(inbox_item, READING, DECISION)
    assert store.item(inbox_item.id).state == "filed_pending_clear"
    assert fresh_filer(vault, store).recover() == [inbox_item.id]
    assert not vault.exists(inbox_item.rel_path) and store.item(inbox_item.id).state == "filed"
    assert len(store.documents_of_type(DocType.health_policy)) == 1
    assert count_files(vault, "Ravi Kumar Rao") == 1
    assert fresh_filer(vault, store).recover() == []  # a second restart has nothing to do


def test_restart_after_stop_between_link_and_database(  # Review Focus 7
    filer, vault, store, inbox_item, monkeypatch
):
    with monkeypatch.context() as mp:
        mp.setattr(records, "write_record", raise_(KeyboardInterrupt()))
        with pytest.raises(KeyboardInterrupt):
            filer.file(inbox_item, READING, DECISION)
    assert store.item(inbox_item.id).state == "filing"
    fresh_filer(vault, store).recover()
    assert store.item(inbox_item.id).state == "filed" and not vault.exists(inbox_item.rel_path)
    assert count_files(vault, "Ravi Kumar Rao") == 1
    assert len(store.documents_of_type(DocType.health_policy)) == 1


def test_restart_after_stop_between_record_and_database(
    filer, vault, store, inbox_item, monkeypatch
):
    with monkeypatch.context() as mp:
        mp.setattr(store, "add_document", raise_(KeyboardInterrupt()))
        with pytest.raises(KeyboardInterrupt):
            filer.file(inbox_item, READING, DECISION)
    (record_file,) = [e.name for e in vault.list_dir("_system/records")]
    fresh_filer(vault, store).recover()
    doc = store.item(inbox_item.id).document_id
    assert record_file == f"{doc}.json"  # the same record, not a second one
    assert len(vault.list_dir("_system/records")) == 1
    assert len(store.documents_of_type(DocType.health_policy)) == 1
    assert count_files(vault, "Ravi Kumar Rao") == 1 and not vault.exists(inbox_item.rel_path)


def test_restart_after_stop_before_the_final_state(filer, vault, store, inbox_item, monkeypatch):
    real = store.update_item

    def stop_at_filed(item_id, **changes):
        if changes.get("state") == "filed":
            raise KeyboardInterrupt
        return real(item_id, **changes)

    with monkeypatch.context() as mp:
        mp.setattr(store, "update_item", stop_at_filed)
        with pytest.raises(KeyboardInterrupt):
            filer.file(inbox_item, READING, DECISION)
    assert not vault.exists(inbox_item.rel_path)  # already cleared
    assert store.item(inbox_item.id).state == "filed_pending_clear"
    assert fresh_filer(vault, store).recover() == [inbox_item.id]
    assert store.item(inbox_item.id).state == "filed" and count_files(vault, "Ravi Kumar Rao") == 1


def test_restart_removes_a_partial_copy_and_requeues(filer, vault, store, inbox_item, now):
    target = "Ravi Kumar Rao/Insurance/x.pdf"
    store.update_item(
        inbox_item.id,
        state="filing",
        target=target,
        pending={"sha256": inbox_item.sha256, "decision": decision_to_json(DECISION)},
    )
    vault.mkdirs("Ravi Kumar Rao/Insurance")
    vault.write_atomic("Ravi Kumar Rao/Insurance/.x.pdf.partial", b"half")
    filer.recover()
    assert (
        vault.list_dir("Ravi Kumar Rao/Insurance") == []
        and store.item(inbox_item.id).state == "queued"
    )
    assert store.claim_next(now).item_id == inbox_item.id
    assert vault.exists(inbox_item.rel_path)


def test_a_stop_before_the_link_requeues_without_a_partial(
    filer, vault, store, inbox_item, now, monkeypatch
):
    with monkeypatch.context() as mp:
        mp.setattr(vault, "copy_verified", raise_(KeyboardInterrupt()))
        with pytest.raises(KeyboardInterrupt):
            filer.file(inbox_item, READING, DECISION)
    assert filer.recover() == [inbox_item.id]
    item = store.item(inbox_item.id)
    assert (item.state, item.target, item.pending) == ("queued", None, None)
    assert vault.exists(inbox_item.rel_path) and count_files(vault, "Ravi Kumar Rao") == 0


def test_recovery_never_deletes_a_file_it_did_not_make(filer, vault, store, inbox_item):
    target = f"{FOLDER}/taken.pdf"
    vault.mkdirs(FOLDER)
    vault.write_atomic(target, b"somebody else's file")
    store.update_item(
        inbox_item.id,
        state="filing",
        target=target,
        pending={"sha256": inbox_item.sha256, "decision": decision_to_json(DECISION)},
    )
    filer.recover()
    assert vault.read_bytes(target) == b"somebody else's file"
    assert vault.exists(inbox_item.rel_path) and store.item(inbox_item.id).state == "queued"


def test_recovery_keeps_an_inbox_file_that_changed_since(
    filer, vault, store, inbox_item, monkeypatch
):
    with monkeypatch.context() as mp:
        mp.setattr(vault, "unlink", raise_(KeyboardInterrupt()))
        with pytest.raises(KeyboardInterrupt):
            filer.file(inbox_item, READING, DECISION)
    vault.unlink(inbox_item.rel_path)
    vault.write_atomic(inbox_item.rel_path, b"%PDF-1.4 a newer file with the same name")
    fresh_filer(vault, store).recover()
    assert vault.read_bytes(inbox_item.rel_path).endswith(b"same name")
    assert store.item(inbox_item.id).state == "filed"


def test_recovery_keeps_the_inbox_copy_when_the_filed_copy_is_gone(
    filer, vault, store, inbox_item, monkeypatch
):
    with monkeypatch.context() as mp:
        mp.setattr(vault, "unlink", raise_(KeyboardInterrupt()))
        with pytest.raises(KeyboardInterrupt):
            filer.file(inbox_item, READING, DECISION)
    doc = store.documents_of_type(DocType.health_policy)[0]
    vault.unlink(doc.rel_path)  # deleted in Drive before the restart
    assert fresh_filer(vault, store).recover() == []
    assert vault.exists(inbox_item.rel_path)
    assert store.item(inbox_item.id).state == "filed_pending_clear"


def test_recover_survives_a_broken_pending_and_reports_it(filer, vault, store, inbox_item):
    target = f"{FOLDER}/x.pdf"
    vault.mkdirs(FOLDER)
    vault.write_atomic(target, b"%PDF-1.4 first policy")
    broken = {
        "doc_id": "d" * 32,
        "created_at": NOW.isoformat(),
        "sha256": inbox_item.sha256,
        "decision": {"nonsense": 1},
        "secret_ref": None,
        "extra_fields": {},
    }
    store.update_item(inbox_item.id, state="filing", target=target, pending=broken)
    assert filer.recover() == []
    assert vault.exists(target) and vault.exists(inbox_item.rel_path)
    assert store.item(inbox_item.id).state == "filing"
    assert filer.activity.entries()[0].step is Step.error


def test_file_new_files_made_bytes_and_leaves_the_photo(filer, vault, store):
    photo = make_item(vault, store, "card.jpg", b"\xff\xd8\xff real photo", kind="jpeg")
    masked = b"\xff\xd8\xff masked copy"
    card = card_reading(secret_values={"number": "4111111111111111"})
    rec = filer.file_new(photo, masked, "jpg", card, CARD_DECISION, "uuid-1", {"last4": "1111"})
    assert rec.rel_path == "Ravi Kumar Rao/Cards/2026-11-20 Card - HDFC Bank ending 1111.jpg"
    assert rec.sha256 == sha(masked) != photo.sha256 and vault.read_bytes(rec.rel_path) == masked
    assert rec.secret_ref == "uuid-1" and rec.fields["last4"] == "1111"
    assert "4111111111111111" not in rec.model_dump_json()
    assert vault.read_bytes(photo.rel_path) == b"\xff\xd8\xff real photo"  # the caller removes it
    done = store.item(photo.id)
    assert (done.state, done.document_id, done.target, done.pending) == (
        "filed",
        rec.id,
        None,
        None,
    )
    assert count_files(vault, "Ravi Kumar Rao/Cards") == 1


def test_file_new_recovers_without_touching_the_photo(filer, vault, store, monkeypatch):
    photo = make_item(vault, store, "card.jpg", b"\xff\xd8\xff real photo", kind="jpeg")
    with monkeypatch.context() as mp:
        mp.setattr(records, "write_record", raise_(KeyboardInterrupt()))
        with pytest.raises(KeyboardInterrupt):
            filer.file_new(photo, b"\xff\xd8\xff masked", "jpg", card_reading(), CARD_DECISION, "u")
    assert fresh_filer(vault, store).recover() == [photo.id]
    done = store.item(photo.id)
    assert done.state == "filed" and len(store.documents_of_type(DocType.card_front)) == 1
    assert not vault.exists(photo.rel_path) and done.rel_path is None  # the photo goes too


def test_file_new_stopped_mid_write_removes_the_partial_and_requeues(
    filer, vault, store, monkeypatch
):
    photo = make_item(vault, store, "card.jpg", b"\xff\xd8\xff real photo", kind="jpeg")
    with monkeypatch.context() as mp:
        mp.setattr(vault, "move", raise_(KeyboardInterrupt()))
        with pytest.raises(KeyboardInterrupt):
            filer.file_new(photo, b"\xff\xd8\xff masked", "jpg", card_reading(), CARD_DECISION, "u")
    assert count_files(vault, "Ravi Kumar Rao") == 1  # the hidden partial
    fresh_filer(vault, store).recover()
    assert count_files(vault, "Ravi Kumar Rao") == 0 and store.item(photo.id).state == "queued"


def test_recover_removes_a_card_photo_left_after_filing(filer, vault, store):
    photo = make_item(vault, store, "card.jpg", b"\xff\xd8\xff real photo", kind="jpeg")
    filer.file_new(photo, b"\xff\xd8\xff masked", "jpg", card_reading(), CARD_DECISION, "u")
    assert filer.recover() == [photo.id]
    assert not vault.exists(photo.rel_path) and store.item(photo.id).rel_path is None
    assert filer.recover() == []  # nothing left to do


def test_clear_card_photo_removes_the_photo_under_the_lock_and_checks_the_hash(filer, vault, store):
    photo = make_item(vault, store, "card.jpg", b"\xff\xd8\xff real photo", kind="jpeg")
    filer.file_new(photo, b"\xff\xd8\xff masked", "jpg", card_reading(), CARD_DECISION, "u")
    assert filer.clear_card_photo(photo.id) is True
    assert not vault.exists(photo.rel_path) and store.item(photo.id).rel_path is None
    assert filer.clear_card_photo(photo.id) is False  # nothing left to clear
    assert not filer.lock.locked()


def test_clear_card_photo_leaves_a_different_file_and_an_item_not_filed(filer, vault, store):
    photo = make_item(vault, store, "card.jpg", b"\xff\xd8\xff real photo", kind="jpeg")
    assert filer.clear_card_photo(photo.id) is False and vault.exists(photo.rel_path)
    filer.file_new(photo, b"\xff\xd8\xff masked", "jpg", card_reading(), CARD_DECISION, "u")
    vault.unlink(photo.rel_path)
    vault.write_atomic(photo.rel_path, b"\xff\xd8\xff another photo")
    assert filer.clear_card_photo(photo.id) is False and vault.exists(photo.rel_path)


def test_recover_leaves_another_file_at_the_photo_name(filer, vault, store):
    photo = make_item(vault, store, "card.jpg", b"\xff\xd8\xff real photo", kind="jpeg")
    filer.file_new(photo, b"\xff\xd8\xff masked", "jpg", card_reading(), CARD_DECISION, "u")
    vault.unlink(photo.rel_path)
    vault.write_atomic(photo.rel_path, b"\xff\xd8\xff another photo")
    assert filer.recover() == [] and vault.exists(photo.rel_path)


def test_undo_moves_it_back_and_holds_it_unless_the_copy_moved(  # Review Focus 8
    filer, vault, store, inbox_item, clash_item
):
    rec = filer.file(inbox_item, READING, DECISION)
    item = filer.undo(rec.id)
    assert item.state == "held" and vault.sha256(item.rel_path) == inbox_item.sha256
    assert store.document(rec.id) is None and not vault.exists(f"_system/records/{rec.id}.json")
    assert item.rel_path.startswith(f"{INBOX}/") and item.document_id is None
    assert not vault.exists(rec.rel_path) and filer.activity.entries()[0].step is Step.undone
    moved = filer.file(clash_item, READING, DECISION)
    vault.move(moved.rel_path, "Ravi Kumar Rao/renamed by hand.pdf")
    with pytest.raises(UndoError, match="no longer at"):
        filer.undo(moved.id)
    assert store.document(moved.id) is not None and vault.exists(
        "Ravi Kumar Rao/renamed by hand.pdf"
    )
    assert vault.exists(f"_system/records/{moved.id}.json")


def test_undo_refuses_a_changed_or_deleted_copy_and_names_the_path(
    filer, vault, store, inbox_item, clash_item
):
    rec = filer.file(inbox_item, READING, DECISION)
    vault.unlink(rec.rel_path)
    vault.write_atomic(rec.rel_path, b"edited in Drive")
    with pytest.raises(
        UndoError, match=f"The filed copy is no longer at {rec.rel_path}\\. Nothing"
    ):
        filer.undo(rec.id)
    other = filer.file(clash_item, READING, DECISION)
    vault.unlink(other.rel_path)
    with pytest.raises(UndoError, match="no longer at"):
        filer.undo(other.id)
    assert store.document(rec.id) and store.document(other.id)
    with pytest.raises(UndoError):
        filer.undo("no-such-document")


def test_undo_uses_a_free_name_in_inbox(filer, vault, store, inbox_item):
    rec = filer.file(inbox_item, READING, DECISION)
    vault.write_atomic(f"{INBOX}/policy.pdf", b"%PDF-1.4 a different file now at that name")
    item = filer.undo(rec.id)
    assert item.rel_path == f"{INBOX}/policy (2).pdf"
    assert vault.read_bytes(f"{INBOX}/policy.pdf").endswith(b"at that name")


def test_a_failed_move_back_changes_nothing(filer, vault, store, inbox_item, monkeypatch):
    rec = filer.file(inbox_item, READING, DECISION)
    monkeypatch.setattr(vault, "move", raise_(OSError("disk went away")))
    with pytest.raises(OSError):
        filer.undo(rec.id)
    assert store.document(rec.id) is not None and store.item(inbox_item.id).state == "filed"
    assert vault.exists(rec.rel_path) and vault.exists(f"_system/records/{rec.id}.json")


def test_refile_after_undo_gives_a_new_record(filer, vault, store, inbox_item):
    first = filer.file(inbox_item, READING, DECISION)
    held = filer.undo(first.id)
    second = filer.file(held, READING, DECISION)
    assert second.id != first.id and second.rel_path == first.rel_path
    assert count_files(vault, "Ravi Kumar Rao") == 1


def test_needs_a_look_moves_the_file_and_undo_puts_it_back(filer, vault, store, inbox_item):
    question = Question(
        Reason.person_unknown, "Whose is it?", "person", [Option("p1", "Ravi Kumar Rao")]
    )
    vault.write_atomic(f"{NEEDS_A_LOOK}/policy.pdf", b"already here")
    reading = card_reading(line_text="4111 1111 1111 1112")
    item = filer.to_needs_a_look(inbox_item, [Reason.person_unknown], question, reading)
    assert item.state == "asked" and item.rel_path == f"{NEEDS_A_LOOK}/policy (2).pdf"
    assert (
        not vault.exists(inbox_item.rel_path) and vault.sha256(item.rel_path) == inbox_item.sha256
    )
    assert item.reasons == [Reason.person_unknown]
    assert item.question["text"] == "Whose is it?" and item.question["options"][0]["value"] == "p1"
    assert "XXXX XXXX XXXX 1112" in str(item.reading)
    entry = filer.activity.entries()[0]
    assert (entry.step, entry.detail) == (Step.needs_a_look, "Whose is it?")
    back = filer.undo_needs_a_look(item.id)
    assert back.state == "held" and back.rel_path == f"{INBOX}/policy.pdf"  # its own name again
    assert vault.sha256(back.rel_path) == inbox_item.sha256
    assert filer.activity.entries()[0].step is Step.undone


def test_needs_a_look_without_a_reading(filer, vault, inbox_item):
    question = Question(
        Reason.damaged, "Cannot read it.", "discard", [Option("discard", "Discard")]
    )
    item = filer.to_needs_a_look(inbox_item, [Reason.damaged], question, None)
    assert item.reading is None and item.state == "asked"


def test_a_decision_that_asks_is_not_filed(filer, vault, store, inbox_item):
    ask: Any = Decision(
        **{**DECISION.__dict__, "outcome": "ask", "reasons": [Reason.person_unknown]}
    )
    with pytest.raises(ValueError):
        filer.file(inbox_item, READING, ask)
    assert vault.exists(inbox_item.rel_path) and store.item(inbox_item.id).state == "reading"
    assert not vault.exists("Ravi Kumar Rao") and not vault.exists("_system/records")


def test_file_names_follow_the_kind(filer, vault, store):
    photo = make_item(vault, store, "IMG_1.jpeg", b"\xff\xd8\xff photo", kind="jpeg")
    assert filer.file(photo, READING, DECISION).rel_path.endswith(".jpg")
    audio = make_item(vault, store, "visit.M4A", b"ID3 audio", kind="audio")
    assert filer.file(audio, READING, DECISION).rel_path.endswith("Star Health.m4a")
