"""Hard stops at every point of every move the filer makes, on APFS (hard links work) and on
Drive (hard links refused), and what `recover` leaves behind."""

import dataclasses
import errno
import os
import sqlite3

import pytest
from vault_synth.household import HOUSEHOLD

from household_vault.activity import Step
from household_vault.filing import records
from household_vault.filing.filer import Filer, TargetGone, UndoError
from household_vault.filing.questions import Option, Question
from household_vault.filing.records import read_record, record_rows
from household_vault.reasons import Reason
from household_vault.vaultroot import INBOX, NEEDS_A_LOOK, VaultGone
from tests.unit.filing.crash import (
    Kill,
    Killed,
    fresh_filer,
    hidden_files,
    no_links,
    records_on_disk,
    sha,
    user_files,
)
from tests.unit.filing.samples import DECISION, READING, card_reading
from tests.unit.filing.test_filer import CARD_DECISION, make_item

DATA = b"%PDF-1.4 first policy"
MODES = pytest.mark.parametrize("drive", [False, True], ids=["apfs", "drive"])
QUESTION = Question(Reason.person_unknown, "Whose is it?", "person", [Option("p1", "Ravi")])


def copies(vault, data):
    return [p for p in user_files(vault) if vault.sha256(p) == sha(data)]


# -- file -----------------------------------------------------------------------------------

FILE_POINTS = [
    "before_copy",
    "during_copy_before_link",
    "right_after_link",
    "after_record",
    "after_db_before_unlink",
    "after_unlink_before_final",
    "at_activity",
]


def arm_file(k, vault, filer, point):
    if point == "before_copy":
        k.before(vault, "copy_verified")
    elif point == "during_copy_before_link":
        k.before(vault, "_place")
    elif point == "right_after_link":
        k.after(vault, "_place")
    elif point == "after_record":
        k.after(records, "write_record")
    elif point == "after_db_before_unlink":
        k.before(vault, "unlink")
    elif point == "after_unlink_before_final":
        k.after(vault, "unlink")
    else:
        k.before(filer.activity, "record")


@MODES
@pytest.mark.parametrize("point", FILE_POINTS)
def test_file_stopped_anywhere_is_finished_or_rolled_back(
    vault, store, activity, clock, now, point, drive
):
    item = make_item(vault, store, "policy.pdf", DATA)
    filer = Filer(vault, store, activity, HOUSEHOLD, clock)
    with pytest.MonkeyPatch.context() as mp:
        if drive:
            no_links(mp)
        arm_file(Kill(mp), vault, filer, point)
        with pytest.raises(Killed):
            filer.file(item, READING, DECISION)
    with pytest.MonkeyPatch.context() as mp:
        if drive:
            no_links(mp)
        fresh_filer(vault, store, HOUSEHOLD).recover()
        done = store.item(item.id)
        assert len(copies(vault, DATA)) == 1 and hidden_files(vault) == []
        if done.state == "filed":
            (doc,) = store.documents_of_type(READING.doc_type)
            assert copies(vault, DATA) == [doc.rel_path]
            assert records_on_disk(vault) == [f"_system/records/{doc.id}.json"]
            row, people, _ = record_rows(read_record(vault, doc.id))
            assert row == doc and sorted(people) == sorted(store.people_of(doc.id))
        else:
            assert done.state == "queued" and (done.target, done.pending) == (None, None)
            assert records_on_disk(vault) == [] and copies(vault, DATA)[0].startswith("Inbox/")
            assert store.claim_next(now).item_id == item.id
            fresh_filer(vault, store, HOUSEHOLD).file(store.item(item.id), READING, DECISION)
            assert len(copies(vault, DATA)) == 1 and not copies(vault, DATA)[0].startswith("Inbox")
        assert fresh_filer(vault, store, HOUSEHOLD).recover() == []


@MODES
@pytest.mark.parametrize(
    "point", ["partial_written", "right_after_place", "after_record", "at_final"]
)
def test_file_new_stopped_anywhere(vault, store, activity, clock, point, drive):
    photo = b"\xff\xd8\xff real photo"
    masked = b"\xff\xd8\xff masked copy"
    item = make_item(vault, store, "card.jpg", photo, kind="jpeg")
    filer = Filer(vault, store, activity, HOUSEHOLD, clock)
    with pytest.MonkeyPatch.context() as mp:
        if drive:
            no_links(mp)
        k = Kill(mp)
        if point == "partial_written":
            k.after(vault, "write_atomic")
        elif point == "right_after_place":
            k.after(vault, "_place")
        elif point == "after_record":
            k.after(records, "write_record")
        else:
            k.before(filer.activity, "record")
        with pytest.raises(Killed):
            filer.file_new(item, masked, "jpg", card_reading(), CARD_DECISION, "uuid-1")
    with pytest.MonkeyPatch.context() as mp:
        if drive:
            no_links(mp)
        fresh_filer(vault, store, HOUSEHOLD).recover()
    assert hidden_files(vault) == []
    done = store.item(item.id)
    if done.state == "filed":
        assert len(copies(vault, masked)) == 1 and len(records_on_disk(vault)) == 1
        assert len(store.documents_of_type(CARD_DOC_TYPE)) == 1
        assert not vault.exists("Inbox/card.jpg")  # a filed card's photo goes too
    else:
        assert done.state == "queued" and copies(vault, masked) == []
        assert vault.read_bytes("Inbox/card.jpg") == photo


CARD_DOC_TYPE = card_reading().doc_type


# -- undo and the Needs a look moves ----------------------------------------------------------

MOVE_POINTS = ["before_move", "after_place", "after_move", "at_activity"]


def arm_move(k, vault, filer, point):
    if point == "before_move":
        k.before(vault, "move")
    elif point == "after_place":
        k.after(vault, "_place")
    elif point == "after_move":
        k.after(vault, "move")
    elif point == "after_record_unlink":
        k.after(vault, "unlink")
    else:
        k.before(filer.activity, "record")


@MODES
@pytest.mark.parametrize("point", [*MOVE_POINTS, "after_record_unlink"])
def test_undo_stopped_anywhere_ends_held_with_one_copy(vault, store, activity, clock, point, drive):
    item = make_item(vault, store, "policy.pdf", DATA)
    filer = Filer(vault, store, activity, HOUSEHOLD, clock)
    with pytest.MonkeyPatch.context() as mp:
        if drive:
            no_links(mp)
        rec = filer.file(item, READING, DECISION)
        arm_move(Kill(mp), vault, filer, point)
        with pytest.raises(Killed):
            filer.undo(rec.id)
    mid = store.item(item.id)
    assert mid.state in ("undoing", "filed") and mid.rel_path is not None
    if mid.state == "undoing":  # the name in Inbox is claimed before the file moves
        assert store.item_at(mid.rel_path).id == item.id
    with pytest.MonkeyPatch.context() as mp:
        if drive:
            no_links(mp)
        assert fresh_filer(vault, store, HOUSEHOLD).recover() == [item.id]
    done = store.item(item.id)
    assert (done.state, done.target, done.pending) == ("held", None, None)
    assert copies(vault, DATA) == [done.rel_path] and done.rel_path.startswith("Inbox/")
    assert store.document(rec.id) is None and records_on_disk(vault) == []
    assert hidden_files(vault) == []
    assert fresh_filer(vault, store, HOUSEHOLD).recover() == []
    with pytest.raises(UndoError):  # nothing left to undo
        fresh_filer(vault, store, HOUSEHOLD).undo(rec.id)


@MODES
@pytest.mark.parametrize("point", MOVE_POINTS)
def test_to_needs_a_look_stopped_anywhere_ends_asked_once(
    vault, store, activity, clock, point, drive
):
    item = make_item(vault, store, "policy.pdf", DATA)
    filer = Filer(vault, store, activity, HOUSEHOLD, clock)
    with pytest.MonkeyPatch.context() as mp:
        if drive:
            no_links(mp)
        arm_move(Kill(mp), vault, filer, point)
        with pytest.raises(Killed):
            filer.to_needs_a_look(item, [Reason.person_unknown], QUESTION, READING)
    mid = store.item(item.id)
    assert mid.state in ("moving", "asked")
    if mid.state == "moving":  # the Inbox name stays claimed while the file may still be there
        assert store.item_at("Inbox/policy.pdf").id == item.id
    with pytest.MonkeyPatch.context() as mp:
        if drive:
            no_links(mp)
        assert fresh_filer(vault, store, HOUSEHOLD).recover() == [item.id]
    done = store.item(item.id)
    assert (done.state, done.target, done.pending) == ("asked", None, None)
    assert copies(vault, DATA) == [done.rel_path] and done.rel_path.startswith(NEEDS_A_LOOK)
    assert done.question["text"] == "Whose is it?" and done.reasons == [Reason.person_unknown]
    assert hidden_files(vault) == [] and fresh_filer(vault, store, HOUSEHOLD).recover() == []


@MODES
@pytest.mark.parametrize("point", MOVE_POINTS)
def test_undo_needs_a_look_stopped_anywhere_ends_held_once(
    vault, store, activity, clock, point, drive
):
    item = make_item(vault, store, "policy.pdf", DATA)
    filer = Filer(vault, store, activity, HOUSEHOLD, clock)
    with pytest.MonkeyPatch.context() as mp:
        if drive:
            no_links(mp)
        asked = filer.to_needs_a_look(item, [Reason.person_unknown], QUESTION, READING)
        arm_move(Kill(mp), vault, filer, point)
        with pytest.raises(Killed):
            filer.undo_needs_a_look(asked.id)
    with pytest.MonkeyPatch.context() as mp:
        if drive:
            no_links(mp)
        assert fresh_filer(vault, store, HOUSEHOLD).recover() == [item.id]
    done = store.item(item.id)
    assert (done.state, done.target, done.pending) == ("held", None, None)
    assert copies(vault, DATA) == [done.rel_path] and done.rel_path.startswith(INBOX)
    assert hidden_files(vault) == [] and fresh_filer(vault, store, HOUSEHOLD).recover() == []


def test_a_move_that_lost_both_files_is_reported_and_left(vault, store, activity, clock):
    item = make_item(vault, store, "policy.pdf", DATA)
    filer = Filer(vault, store, activity, HOUSEHOLD, clock)
    with pytest.MonkeyPatch.context() as mp:
        arm_move(Kill(mp), vault, filer, "before_move")
        with pytest.raises(Killed):
            filer.to_needs_a_look(item, [Reason.person_unknown], QUESTION, READING)
    vault.unlink("Inbox/policy.pdf")  # removed in Drive while the app was down
    assert fresh_filer(vault, store, HOUSEHOLD).recover() == []
    assert store.item(item.id).state == "moving"
    assert filer.activity.entries()[0].step is Step.error


def test_a_move_whose_destination_was_taken_finishes_under_a_free_name(
    vault, store, activity, clock
):
    item = make_item(vault, store, "policy.pdf", DATA)
    filer = Filer(vault, store, activity, HOUSEHOLD, clock)
    with pytest.MonkeyPatch.context() as mp:
        arm_move(Kill(mp), vault, filer, "before_move")
        with pytest.raises(Killed):
            filer.to_needs_a_look(item, [Reason.person_unknown], QUESTION, READING)
    dest = store.item(item.id).target
    vault.write_atomic(dest, b"somebody else's file")
    assert fresh_filer(vault, store, HOUSEHOLD).recover() == [item.id]
    done = store.item(item.id)
    assert vault.read_bytes(dest) == b"somebody else's file" and not vault.exists(
        "Inbox/policy.pdf"
    )
    assert (done.state, done.rel_path) == ("asked", "Needs a look/policy (2).pdf")
    assert vault.sha256(done.rel_path) == sha(DATA)


# -- an ordinary exception after the link -------------------------------------------------------


def boom(exc):
    def raiser(*a, **k):
        raise exc

    return raiser


@pytest.mark.parametrize("where", ["record_write", "db_insert"])
def test_an_error_before_the_commit_rolls_everything_back(vault, store, activity, clock, where):
    item = make_item(vault, store, "policy.pdf", DATA)
    filer = Filer(vault, store, activity, HOUSEHOLD, clock)
    with pytest.MonkeyPatch.context() as mp:
        if where == "record_write":
            mp.setattr(records, "write_record", boom(OSError(errno.EIO, "Drive refused")))
        else:
            mp.setattr(store, "add_document", boom(sqlite3.IntegrityError("FOREIGN KEY")))
        with pytest.raises((OSError, sqlite3.IntegrityError)):
            filer.file(item, READING, DECISION)
    after = store.item(item.id)
    assert (after.state, after.target, after.pending) == ("reading", None, None)
    assert copies(vault, DATA) == ["Inbox/policy.pdf"] and records_on_disk(vault) == []
    assert hidden_files(vault) == [] and store.documents_of_type(READING.doc_type) == []
    # the worker's fallback now leaves exactly one copy
    asked = filer.to_needs_a_look(after, [Reason.read_failed], QUESTION, READING)
    assert copies(vault, DATA) == [asked.rel_path] and filer.recover() == []


def test_an_inbox_unlink_error_after_the_commit_is_not_a_failure(vault, store, activity, clock):
    item = make_item(vault, store, "policy.pdf", DATA)
    filer = Filer(vault, store, activity, HOUSEHOLD, clock)
    real = vault.unlink

    def refuse_inbox(rel):
        if rel.startswith(INBOX):
            raise PermissionError(errno.EPERM, "Drive refused")
        real(rel)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(vault, "unlink", refuse_inbox)
        rec = filer.file(item, READING, DECISION)  # no exception: the document is filed
    assert store.document(rec.id) is not None
    assert store.item(item.id).state == "filed_pending_clear" and vault.exists("Inbox/policy.pdf")
    with pytest.raises(ValueError):  # the worker cannot move it to Needs a look now
        filer.to_needs_a_look(store.item(item.id), [Reason.read_failed], QUESTION, READING)
    assert filer.activity.entries()[0].step is Step.error
    assert filer.recover() == [item.id]
    assert store.item(item.id).state == "filed" and not vault.exists("Inbox/policy.pdf")
    assert len(copies(vault, DATA)) == 1


def test_a_rollback_that_cannot_remove_the_copy_leaves_it_for_recovery(
    vault, store, activity, clock
):
    item = make_item(vault, store, "policy.pdf", DATA)
    filer = Filer(vault, store, activity, HOUSEHOLD, clock)

    def refuse(rel):
        raise PermissionError(errno.EPERM, "Drive refused")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(records, "write_record", boom(OSError(errno.EIO, "Drive refused")))
        mp.setattr(vault, "unlink", refuse)
        with pytest.raises(OSError, match="Drive refused"):
            filer.file(item, READING, DECISION)
    assert store.item(item.id).state == "filing"  # recover finishes it rather than losing it
    assert filer.recover() == [item.id] and len(copies(vault, DATA)) == 1
    assert store.item(item.id).state == "filed"


BUSY = ["filing", "filed_pending_clear", "undoing", "moving", "filed"]


@pytest.mark.parametrize("state", BUSY)
def test_an_item_in_the_middle_of_something_is_refused(vault, store, activity, clock, state):
    item = make_item(vault, store, "policy.pdf", DATA)
    filer = Filer(vault, store, activity, HOUSEHOLD, clock)
    store.update_item(item.id, state=state)
    stale = dataclasses.replace(item, state="reading")  # the caller's copy is out of date
    with pytest.raises(ValueError, match=r"busy or already"):
        filer.file(stale, READING, DECISION)
    with pytest.raises(ValueError, match=r"busy or already"):
        filer.file_new(stale, b"x", "jpg", READING, DECISION, None)
    with pytest.raises(ValueError, match=r"busy or already"):
        filer.to_needs_a_look(stale, [Reason.read_failed], QUESTION, READING)
    assert vault.exists("Inbox/policy.pdf") and not vault.exists("Ravi Kumar Rao")
    assert store.item(item.id).state == state


def test_a_linked_person_outside_the_household_is_refused_before_any_copy(
    vault, store, activity, clock
):
    item = make_item(vault, store, "policy.pdf", DATA)
    filer = Filer(vault, store, activity, HOUSEHOLD, clock)
    bad = dataclasses.replace(DECISION, linked=["p1", "p9"])
    with pytest.raises(ValueError, match="p9"):
        filer.file(item, READING, bad)
    assert store.item(item.id).state == "reading" and not vault.exists("Ravi Kumar Rao")
    assert not vault.exists("_system/records")


def test_an_extra_field_outside_the_schema_is_refused_before_any_copy(
    vault, store, activity, clock
):
    item = make_item(vault, store, "policy.pdf", DATA)
    filer = Filer(vault, store, activity, HOUSEHOLD, clock)
    with pytest.raises(ValueError, match="pin"):
        filer.file(item, READING, DECISION, None, {"pin": "4321"})
    assert store.item(item.id).state == "reading" and not vault.exists("Ravi Kumar Rao")


# -- races at the target, vanished folders ------------------------------------------------------


@pytest.mark.parametrize("same", [False, True], ids=["other bytes", "identical bytes"])
def test_a_file_that_lands_at_the_target_first_is_never_adopted(
    vault, store, activity, clock, same
):
    item = make_item(vault, store, "policy.pdf", DATA)
    filer = Filer(vault, store, activity, HOUSEHOLD, clock)
    real = vault.copy_verified
    landed = b"\x00synced in" if not same else DATA

    def racing(src, dst, digest):
        vault.write_atomic(dst, landed)
        return real(src, dst, digest)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(vault, "copy_verified", racing)
        with pytest.raises(FileExistsError):
            filer.file(item, READING, DECISION)
    after = store.item(item.id)
    assert (after.state, after.target, after.pending) == ("reading", None, None)
    assert store.documents_of_type(READING.doc_type) == [] and records_on_disk(vault) == []
    assert vault.exists("Inbox/policy.pdf") and filer.recover() == []
    taken = "Ravi Kumar Rao/Insurance/2026-04-01 Health policy - Star Health.pdf"
    assert vault.read_bytes(taken) == landed  # the other file is untouched
    rec = filer.file(after, READING, DECISION)  # a retry takes the next free name
    assert rec.rel_path.endswith("Star Health (2).pdf")


def test_a_vanished_target_folder_is_not_reported_as_a_gone_file(vault, store, activity, clock):
    item = make_item(vault, store, "policy.pdf", DATA)
    filer = Filer(vault, store, activity, HOUSEHOLD, clock)
    real = vault.copy_verified

    def folder_removed(src, dst, digest):
        os.rmdir(vault.path("Ravi Kumar Rao/Insurance"))
        return real(src, dst, digest)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(vault, "copy_verified", folder_removed)
        with pytest.raises(TargetGone) as caught:
            filer.file(item, READING, DECISION)
    assert not isinstance(caught.value, VaultGone) and vault.exists("Inbox/policy.pdf")
    after = store.item(item.id)
    assert (after.state, after.target, after.pending) == ("reading", None, None)


def test_a_file_gone_from_inbox_is_reported_as_gone(vault, store, activity, clock):
    item = make_item(vault, store, "policy.pdf", DATA)
    filer = Filer(vault, store, activity, HOUSEHOLD, clock)
    vault.unlink(item.rel_path)
    with pytest.raises(VaultGone):
        filer.file(item, READING, DECISION)
    after = store.item(item.id)
    assert (after.state, after.target, after.pending) == ("reading", None, None)
    assert not vault.exists("_system/records")


# -- undo of a card, masking by the effective type ------------------------------------------------


def test_undo_of_a_document_with_a_secret_is_refused_and_changes_nothing(
    vault, store, activity, clock
):
    photo = make_item(vault, store, "card.jpg", b"\xff\xd8\xff real photo", kind="jpeg")
    filer = Filer(vault, store, activity, HOUSEHOLD, clock)
    rec = filer.file_new(
        photo, b"\xff\xd8\xff masked", "jpg", card_reading(), CARD_DECISION, "kp-1"
    )
    before = (user_files(vault), records_on_disk(vault), store.item(photo.id))
    with pytest.raises(UndoError, match="cards"):
        filer.undo(rec.id)
    assert (user_files(vault), records_on_disk(vault), store.item(photo.id)) == before
    assert store.document(rec.id) is not None


def test_an_override_to_other_masks_every_long_run_in_what_is_stored(vault, store, activity, clock):
    item = make_item(vault, store, "x.pdf", b"%PDF-1.4 y")
    store.update_item(item.id, overrides={"doc_type": "other"})
    filer = Filer(vault, store, activity, HOUSEHOLD, clock)
    from tests.unit.filing.samples import reading_with_box

    reading = reading_with_box(text="ref 4111 1111 1111 1112")  # read as a health policy
    asked = filer.to_needs_a_look(store.item(item.id), [Reason.person_unknown], QUESTION, reading)
    assert asked.reading["pages"][0]["lines"][0]["text"] == "ref XXXX XXXX XXXX 1112"


def test_a_cvv_never_reaches_the_item_row(vault, store, activity, clock):
    item = make_item(vault, store, "back.jpg", b"\xff\xd8\xff back", kind="jpeg")
    filer = Filer(vault, store, activity, HOUSEHOLD, clock)
    card = card_reading(secret_values={"cvv": "123"}, line_text="CVV 123")
    asked = filer.to_needs_a_look(item, [Reason.person_unknown], QUESTION, card)
    assert asked.reading["pages"][0]["lines"][0]["text"] == "CVV XXX"


# -- fix round 2 ----------------------------------------------------------------------------------


class RaceLock:
    """Stands in for `Filer.lock`: runs `hook` once, just before the lock is first taken."""

    def __init__(self, real, hook):
        self.real, self.hook = real, hook

    def __enter__(self):
        hook, self.hook = self.hook, None
        if hook:
            hook()
        return self.real.__enter__()

    def __exit__(self, *exc):
        return self.real.__exit__(*exc)


def test_to_needs_a_look_checks_the_item_inside_the_lock(vault, store, activity, clock):
    item = make_item(vault, store, "policy.pdf", DATA)
    filer = Filer(vault, store, activity, HOUSEHOLD, clock)
    stale = filer.to_needs_a_look(item, [Reason.person_unknown], QUESTION, READING)
    filer.lock = RaceLock(filer.lock, lambda: filer.undo_needs_a_look(stale.id))
    again = filer.to_needs_a_look(stale, [Reason.person_unknown], QUESTION, READING)
    assert again.state == "asked" and copies(vault, DATA) == [again.rel_path]
    assert again.rel_path.startswith(NEEDS_A_LOOK) and user_files(vault) == [again.rel_path]


def test_asking_again_keeps_the_file_where_it_is(vault, store, activity, clock):
    item = make_item(vault, store, "policy.pdf", DATA)
    filer = Filer(vault, store, activity, HOUSEHOLD, clock)
    first = filer.to_needs_a_look(item, [Reason.person_unknown], QUESTION, READING)
    other = Question(Reason.read_failed, "Could not read it.", "retry", [Option("retry", "Retry")])
    second = filer.to_needs_a_look(first, [Reason.read_failed], other, READING)
    assert second.rel_path == first.rel_path == "Needs a look/policy.pdf"
    assert second.state == "asked" and second.reasons == [Reason.read_failed]
    assert second.question["text"] == "Could not read it."
    assert user_files(vault) == [first.rel_path] and hidden_files(vault) == []
    entry = filer.activity.entries()[0]
    assert (entry.step, entry.detail) == (Step.needs_a_look, "Could not read it.")


@MODES
@pytest.mark.parametrize("which", ["undo", "undo_needs_a_look"])
def test_a_stopped_move_whose_inbox_name_was_taken_finishes_under_a_free_name(
    vault, store, activity, clock, which, drive
):
    item = make_item(vault, store, "policy.pdf", DATA)
    filer = Filer(vault, store, activity, HOUSEHOLD, clock)
    with pytest.MonkeyPatch.context() as mp:
        if drive:
            no_links(mp)
        if which == "undo":
            rec = filer.file(item, READING, DECISION)
            arm_move(Kill(mp), vault, filer, "before_move")
            with pytest.raises(Killed):
                filer.undo(rec.id)
        else:
            asked = filer.to_needs_a_look(item, [Reason.person_unknown], QUESTION, READING)
            arm_move(Kill(mp), vault, filer, "before_move")
            with pytest.raises(Killed):
                filer.undo_needs_a_look(asked.id)
    taken = store.item(item.id).target
    vault.write_atomic(taken, b"a different file synced in")
    with pytest.MonkeyPatch.context() as mp:
        if drive:
            no_links(mp)
        assert fresh_filer(vault, store, HOUSEHOLD).recover() == [item.id]
    done = store.item(item.id)
    assert (done.state, done.target, done.pending) == ("held", None, None)
    assert done.rel_path == taken.replace(".pdf", " (2).pdf")
    assert vault.read_bytes(taken) == b"a different file synced in"
    assert vault.sha256(done.rel_path) == sha(DATA) and hidden_files(vault) == []
    assert fresh_filer(vault, store, HOUSEHOLD).recover() == []


def test_a_target_folder_that_cannot_be_made_is_not_a_gone_file(vault, store, activity, clock):
    item = make_item(vault, store, "policy.pdf", DATA)
    filer = Filer(vault, store, activity, HOUSEHOLD, clock)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(vault, "mkdirs", boom(VaultGone("no such file or folder")))
        with pytest.raises(TargetGone) as caught:
            filer.file(item, READING, DECISION)
    assert not isinstance(caught.value, VaultGone) and vault.exists("Inbox/policy.pdf")
    after = store.item(item.id)
    assert (after.state, after.target, after.pending) == ("reading", None, None)
