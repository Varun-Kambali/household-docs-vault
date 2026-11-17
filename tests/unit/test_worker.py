import threading

import pytest

from household_vault.activity import Step
from household_vault.doctypes import DocType
from household_vault.reasons import Reason
from household_vault.vaultroot import INBOX, CopyMismatch
from household_vault.worker import HoldCards
from tests.conftest import drop, fileable
from tests.fakes import OpenGateCards, TruthModels


def test_two_identical_files_file_once(world):  # Review Focus 6
    d = fileable(DocType.tax_invoice)
    drop(world.vault, "a.pdf", d.data)
    drop(world.vault, "a (1).pdf", d.data)
    world.drain()
    assert len(world.store.documents_of_type(DocType.tax_invoice)) == 1
    assert [i.reasons for i in world.store.items(["asked"])] == [[Reason.duplicate]]


def test_a_file_removed_while_reading_ends_as_gone(make_world):  # Review Focus 9
    models = TruthModels()
    w = make_world(models=models)
    models.on_fill = lambda: w.vault.unlink("Inbox/a.pdf")
    drop(w.vault, "a.pdf", fileable(DocType.health_policy).data)
    w.drain()
    (item,) = w.store.items(["gone"])
    assert item.document_id is None and w.activity.entries()[0].step is Step.gone
    assert not w.store.documents_of_type(DocType.health_policy)


def test_reader_down_waits_and_tries_again(make_world):
    w = make_world(models=TruthModels(down_first=1))
    drop(w.vault, "a.pdf", fileable(DocType.health_policy).data)
    w.drain()
    entry = w.activity.entries()[0]
    assert (entry.outcome, entry.detail) == (
        "waiting",
        "Waiting for the reader (Ollama is not running)",
    )
    w.clock.advance(seconds=31)
    w.drain()
    assert w.store.items(["filed"])


def test_the_wait_doubles_up_to_ten_minutes(make_world):
    w = make_world(models=TruthModels(down_first=20))
    drop(w.vault, "a.pdf", fileable(DocType.health_policy).data)
    waits = []
    for _ in range(8):
        w.drain()
        (job,) = [j for j in _jobs(w) if j.state == "queued"]
        assert job.not_before is not None
        waits.append(round((job.not_before - w.clock.t).total_seconds()))
        w.clock.advance(seconds=waits[-1] + 1)
    assert waits == [30, 60, 120, 240, 480, 600, 600, 600]


def _jobs(w):
    with w.store.lock:
        rows = w.store.conn.execute("select id from jobs").fetchall()
    from household_vault.db import _job

    with w.store.lock:
        return [
            _job(w.store.conn.execute("select * from jobs where id = ?", (r[0],)).fetchone())
            for r in rows
        ]


def test_a_copy_that_does_not_match_is_retried_once_then_asked(make_world, monkeypatch):  # r17
    w = make_world()
    real = w.vault.copy_verified
    failures = iter([True, False, True, True])

    def flaky(src, dst, sha):
        if next(failures):
            raise CopyMismatch("copy does not match")
        real(src, dst, sha)

    monkeypatch.setattr(w.vault, "copy_verified", flaky)
    drop(w.vault, "a.pdf", fileable(DocType.tax_invoice).data)
    drop(w.vault, "b.pdf", fileable(DocType.warranty_card).data)
    w.drain()
    assert len(w.store.items(["filed"])) == 1
    assert [i.reasons for i in w.store.items(["asked"])] == [[Reason.copy_mismatch]]


def test_a_job_cut_off_by_a_stop_runs_again(make_world, now):  # ruling 14
    w = make_world()
    drop(w.vault, "a.pdf", fileable(DocType.tax_invoice).data)
    w.worker.scan()
    w.store.claim_next(now)  # claimed, then the app stopped
    w.worker.start_up()
    w.drain()
    assert w.store.items(["filed"])
    assert w.store.running_jobs() == []


def test_recordings_and_inbox_cards_wait_while_the_gate_is_closed(world):  # HoldCards, r16
    drop(world.vault, "visit.m4a", b"\x00\x00\x00\x20ftypM4A " + b"\x00" * 64)
    card = fileable(DocType.card_front, variant="photo")
    drop(world.vault, "card.jpg", card.data)
    world.drain()
    assert [i.reasons for i in world.store.items(["asked"])] == [[Reason.recording]]
    (held,) = world.store.items(["waiting_secrets"])
    assert (
        held.rel_path == "Inbox/card.jpg" and world.vault.read_bytes("Inbox/card.jpg") == card.data
    )
    (entry,) = [e for e in world.activity.entries() if e.step is Step.waiting]
    assert (entry.step, entry.outcome, entry.detail) == (
        Step.waiting,
        "waiting",
        "Waiting for the secrets store to be unlocked",
    )


def test_waiting_cards_are_read_again_once_the_gate_opens(world):
    card = fileable(DocType.card_front, variant="photo")
    drop(world.vault, "card.jpg", card.data)
    world.drain()
    assert world.store.items(["waiting_secrets"])
    gate = OpenGateCards()
    gate.filer = world.filer
    world.worker.cards = gate
    world.drain()
    (item,) = world.store.items(["filed"])
    docs = world.store.documents_of_type(DocType.card_front)
    assert len(docs) == 1 and docs[0].secret_ref == "fake-entry"
    assert item.rel_path is None and world.vault.list_dir(INBOX) == []


def test_hold_cards_is_closed():
    assert HoldCards().ready() is False


def test_progress_counts_the_batch(world):
    drop(world.vault, "a.pdf", fileable(DocType.tax_invoice).data)
    drop(world.vault, "b.pdf", fileable(DocType.warranty_card).data)
    drop(world.vault, "empty.pdf", b"")
    world.drain()
    p = world.worker.progress()
    assert (p.waiting, p.total_in_batch, p.done_in_batch, p.asked_in_batch) == (0, 3, 3, 1)
    assert p.current is None and p.batch_started_at is not None
    drop(world.vault, "c.pdf", fileable(DocType.lab_report).data)
    world.drain()
    p = world.worker.progress()
    assert (p.total_in_batch, p.done_in_batch) == (1, 1)


def test_a_held_file_removed_in_drive_ends_as_gone(world):
    d = fileable(DocType.warranty_card)
    drop(world.vault, "w.pdf", d.data)
    world.drain()
    (doc,) = world.store.documents_of_type(DocType.warranty_card)
    world.actions.undo_document(doc.id)
    (held,) = world.store.items(["held"])
    assert held.rel_path is not None
    world.vault.unlink(held.rel_path)
    world.drain()
    world.drain()  # gone once it is missing on a second scan
    assert world.store.item(held.id).state == "gone"
    drop(world.vault, "w.pdf", d.data)  # the same name can come in again
    world.drain()
    assert world.store.documents_of_type(DocType.warranty_card)


def test_an_unexpected_error_asks_and_names_only_its_type(make_world, monkeypatch):
    w = make_world()
    drop(w.vault, "a.pdf", fileable(DocType.tax_invoice).data)

    def boom(*args, **kwargs):
        raise RuntimeError("secret detail 4111")

    monkeypatch.setattr(w.worker.engines.pages, "read_pages", boom)
    w.drain()
    (item,) = w.store.items(["asked"])
    assert item.reasons == [Reason.read_failed]
    errors = [e for e in w.activity.entries() if e.step is Step.error]
    assert [e.detail for e in errors] == ["Could not read this file: RuntimeError"]


def test_a_busy_item_is_never_routed_or_filed_again(world):
    d = fileable(DocType.tax_invoice)
    drop(world.vault, "a.pdf", d.data)
    world.drain()
    (item,) = world.store.items(["filed"])
    world.store.requeue(item.id)  # a stale job for a filed item
    world.store.update_item(item.id, state="filed")
    world.drain()
    assert len(world.store.documents_of_type(DocType.tax_invoice)) == 1
    assert world.store.item(item.id).state == "filed"


def test_run_forever_starts_up_and_stops(world):
    drop(world.vault, "a.pdf", fileable(DocType.tax_invoice).data)
    stop = threading.Event()
    original = world.worker.drain

    def drain_then_stop() -> None:
        original()
        stop.set()

    world.worker.drain = drain_then_stop  # type: ignore[method-assign]
    world.worker.run_forever(stop)
    assert world.store.items(["filed"])


def test_scan_leaves_held_items_alone(world):
    drop(world.vault, "w.pdf", fileable(DocType.warranty_card).data)
    world.drain()
    (doc,) = world.store.documents_of_type(DocType.warranty_card)
    world.actions.undo_document(doc.id)
    assert world.worker.scan() == 0


# -- fix round 1: outages, the busy guard, small counts ------------------------------------------

import os  # noqa: E402
from pathlib import Path  # noqa: E402

from household_vault.filing import records  # noqa: E402
from household_vault.filing.filer import BUSY  # noqa: E402
from household_vault.vaultroot import NEEDS_A_LOOK, VaultGone  # noqa: E402


def _unmount(w):
    root = w.vault.root
    aside = Path(str(root) + "-unmounted")
    w.vault.mode = "app"  # app mode never makes the root again
    os.rename(root, aside)
    return lambda: os.rename(aside, root)


def test_a_held_item_stays_held_while_the_vault_is_away(world):
    drop(world.vault, "w.pdf", fileable(DocType.warranty_card).data)
    world.drain()
    (doc,) = world.store.documents_of_type(DocType.warranty_card)
    held = world.actions.undo_document(doc.id)
    back = _unmount(world)
    world.drain()
    world.drain()
    assert world.store.item(held.id).state == "held"
    back()
    world.drain()
    world.drain()
    assert world.store.item(held.id).state == "held"


def test_a_file_that_is_missing_for_one_scan_only_is_not_gone(world):
    drop(world.vault, "w.pdf", fileable(DocType.warranty_card).data)
    world.drain()
    (doc,) = world.store.documents_of_type(DocType.warranty_card)
    held = world.actions.undo_document(doc.id)
    data = world.vault.read_bytes(held.rel_path)
    world.vault.unlink(held.rel_path)
    world.worker.scan()  # missing once
    world.vault.write_atomic(held.rel_path, data)
    world.worker.scan()  # back
    world.vault.unlink(held.rel_path)
    world.worker.scan()  # missing once more, the count starts again
    assert world.store.item(held.id).state == "held"
    world.worker.scan()  # missing on a second scan
    assert world.store.item(held.id).state == "gone"


def test_the_second_missing_scan_waits_for_the_settle_time(make_world):
    w = make_world()
    w.worker.settings = w.worker.settings.model_copy(update={"settle_seconds": 10.0})
    drop(w.vault, "w.pdf", fileable(DocType.warranty_card).data)
    w.worker.scan()
    w.clock.advance(seconds=11)
    w.worker.scan()
    w.drain()
    (doc,) = w.store.documents_of_type(DocType.warranty_card)
    held = w.actions.undo_document(doc.id)
    w.vault.unlink(held.rel_path)
    w.worker.scan()
    w.clock.advance(seconds=5)
    w.worker.scan()
    assert w.store.item(held.id).state == "held"
    w.clock.advance(seconds=6)
    w.worker.scan()
    assert w.store.item(held.id).state == "gone"


@pytest.mark.parametrize("how", ["retry", "type", "keep_both", "unlock"])
def test_a_needs_a_look_job_waits_out_a_vault_outage(make_world, how):
    w = make_world(models=TruthModels(patch={"patient": "Anita Sharma"}))
    if how == "unlock":
        d = fileable(DocType.health_policy, variant="locked")
    elif how == "keep_both":
        d = fileable(DocType.tax_invoice)
    else:
        d = fileable(DocType.prescription)
    drop(w.vault, "a.pdf", d.data)
    if how == "keep_both":
        drop(w.vault, "b.pdf", d.data)
    w.drain()
    item = w.store.items(["asked"])[-1]
    if how == "retry":
        w.actions.retry(item.id)
    elif how == "type":
        w.actions.answer(item.id, "type", "lab_report")
    elif how == "keep_both":
        w.actions.answer(item.id, "copy", "keep_both")
    else:
        w.actions.unlock(item.id, d.doc.password)
    back = _unmount(w)
    w.drain()
    assert w.store.item(item.id).state == "queued"
    back()
    w.clock.advance(seconds=700)
    w.drain()
    after = w.store.item(item.id)
    assert after.state in ("filed", "asked")
    claimed = {i.rel_path for i in w.store.items(["asked", "held", "queued"])}
    on_disk = {f.name for f in (w.vault.root / NEEDS_A_LOOK).iterdir()}
    assert {Path(p).name for p in claimed if p} >= on_disk
    assert w.worker.pending_passwords == {}


def test_a_missing_file_with_the_vault_present_still_ends_gone(world):
    drop(world.vault, "a.pdf", fileable(DocType.tax_invoice).data)
    world.worker.scan()
    world.vault.unlink("Inbox/a.pdf")
    world.drain()
    assert [i.state for i in world.store.items(["gone"])] == ["gone"]


def test_a_vanished_file_never_ends_a_busy_item_as_gone(make_world, monkeypatch):
    w = make_world()
    drop(w.vault, "a.pdf", fileable(DocType.tax_invoice).data)

    def gone(*args, **kwargs):
        raise VaultGone("the records folder vanished")

    monkeypatch.setattr(records, "write_record", gone)
    real_unlink = w.vault.unlink

    def unlink(rel):
        if not rel.startswith((INBOX, "_system")):
            raise OSError("Drive refused")
        real_unlink(rel)

    monkeypatch.setattr(w.vault, "unlink", unlink)
    w.worker.scan()
    w.worker.run_once()
    (item,) = w.store.items(["filing"])
    assert item.state in BUSY
    assert not w.store.items(["gone"])


def test_an_item_held_after_a_double_failure_counts_as_finished(make_world, monkeypatch):
    w = make_world()
    drop(w.vault, "a.pdf", fileable(DocType.tax_invoice).data)

    def boom(*args, **kwargs):
        raise RuntimeError("x")

    monkeypatch.setattr(w.worker.engines.pages, "read_pages", boom)
    monkeypatch.setattr(w.filer, "to_needs_a_look", boom)
    w.drain()
    assert [i.state for i in w.store.items(["held"])] == ["held"]
    p = w.worker.progress()
    assert (p.total_in_batch, p.done_in_batch) == (1, 1)


def test_a_skipped_job_leaves_no_password_in_memory(world):
    d = fileable(DocType.health_policy, variant="locked")
    drop(world.vault, "policy.pdf", d.data)
    world.drain()
    (item,) = world.store.items(["asked"])
    world.worker.pending_passwords[item.id] = d.doc.password
    world.store.update_item(item.id, state="discarded")
    world.store.enqueue(item.id, "process")
    world.drain()
    assert world.worker.pending_passwords == {}


def test_a_successful_job_resets_the_copy_mismatch_count(make_world, monkeypatch):
    w = make_world()
    real = w.vault.copy_verified
    failures = iter([True, False])

    def flaky(src, dst, sha):
        if next(failures):
            raise CopyMismatch("copy does not match")
        real(src, dst, sha)

    monkeypatch.setattr(w.vault, "copy_verified", flaky)
    drop(w.vault, "a.pdf", fileable(DocType.tax_invoice).data)
    w.drain()
    (item,) = w.store.items(["filed"])
    assert not item.overrides.get("copy_mismatches")
