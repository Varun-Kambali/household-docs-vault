"""A file re-checked while its identical copy waits is not a duplicate of that copy (I3)."""

from vault_synth.sets import load_set, locked_password

from household_vault.doctypes import DocType
from household_vault.reasons import Reason
from tests.conftest import EVAL_V1, drop, fileable


def test_a_locked_pdf_dropped_twice_files_once_unlocked(make_world):
    w = make_world()
    doc = next(
        d
        for d in load_set(EVAL_V1)
        if d.split == "val" and d.variant == "locked" and not d.expected_ask
    )
    data = (EVAL_V1 / doc.files[0]).read_bytes()
    drop(w.vault, "a.pdf", data)
    drop(w.vault, "a (1).pdf", data)
    w.drain()
    locked = next(i for i in w.store.items(["asked"]) if Reason.locked in i.reasons)
    w.actions.unlock(locked.id, locked_password(doc.base_id))
    w.drain()
    assert len(w.store.items(["filed"])) == 1
    (waiting,) = w.store.items(["asked"])
    assert Reason.duplicate in waiting.reasons


def test_an_undone_and_retried_original_is_not_a_duplicate_of_its_copy(make_world):
    w = make_world()
    d = fileable(DocType.tax_invoice)
    drop(w.vault, "a.pdf", d.data)
    drop(w.vault, "b.pdf", d.data)
    w.drain()
    (filed,) = w.store.items(["filed"])
    w.actions.undo_document(filed.document_id)
    (held,) = w.store.items(["held"])
    w.actions.retry(held.id)
    w.drain()
    assert len(w.store.items(["filed"])) == 1
