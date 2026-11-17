import pytest

from household_vault.actions import AnswerError, PartlyAnswered
from household_vault.doctypes import DocType
from household_vault.filing.filer import UndoError
from household_vault.reasons import Reason
from tests.conftest import drop, everything_written, fileable
from tests.fakes import TruthModels


def test_a_locked_pdf_files_after_unlocking_and_its_password_is_kept_nowhere(world):
    d = fileable(DocType.health_policy, variant="locked")
    drop(world.vault, "policy.pdf", d.data)
    world.drain()
    (item,) = world.store.items(["asked"])
    assert item.reasons == [Reason.locked]
    with pytest.raises(AnswerError):
        world.actions.unlock(item.id, "wrong")
    assert world.worker.pending_passwords == {}
    world.actions.unlock(item.id, d.doc.password)
    world.drain()
    assert world.store.item(item.id).state == "filed" and world.worker.pending_passwords == {}
    assert d.doc.password.encode() not in everything_written(world)
    assert not any(d.doc.password in e.detail for e in world.activity.entries())


def test_a_wrong_password_says_so_plainly(world):
    d = fileable(DocType.health_policy, variant="locked")
    drop(world.vault, "policy.pdf", d.data)
    world.drain()
    (item,) = world.store.items(["asked"])
    with pytest.raises(AnswerError, match="That password did not open the PDF"):
        world.actions.unlock(item.id, "wrong")


def test_saving_a_password_waits_for_the_secrets_store(world):
    with pytest.raises(AnswerError, match="Saving passwords comes with the secrets store"):
        world.actions.unlock(1, "x", save=True)


def test_answering_a_person_files_one_or_many(make_world):
    w = make_world(models=TruthModels(patch={"patient": "Anita Sharma"}))
    for name, t in (("a.pdf", DocType.prescription), ("b.pdf", DocType.lab_report)):
        drop(w.vault, name, fileable(t).data)
    w.drain()
    first, second = w.store.items(["asked"])
    w.actions.answer(first.id, "person", "p2")
    w.actions.answer_many([second.id], "p3")
    w.drain()
    docs = [w.store.document(w.store.item(i.id).document_id) for i in (first, second)]
    assert [d.owner for d in docs] == ["p2", "p3"]
    assert docs[0].rel_path.startswith("Kavita Rao/Medical/Reports/")


def test_a_person_who_is_not_in_the_household_is_refused(world, asked_item):
    with pytest.raises(AnswerError):
        world.actions.answer(asked_item.id, "person", "p99")


def test_a_typed_card_number_is_refused(world, asked_item):
    with pytest.raises(AnswerError, match="Card numbers are added from a photo, not typed"):
        world.actions.answer(asked_item.id, "field", "4111111111111111", field="number")
    assert world.store.item(asked_item.id).state == "asked"


def test_a_field_answer_is_stored_in_the_overrides_only(make_world):
    w = make_world(models=TruthModels(patch={"policy_number": None}))
    drop(w.vault, "p.pdf", fileable(DocType.health_policy).data)
    w.drain()
    (item,) = w.store.items(["asked"])
    assert item.reasons == [Reason.missing_required]
    w.actions.answer(item.id, "field", "PN-481516", field="policy_number")
    assert w.store.item(item.id).overrides["fields"] == {"policy_number": "PN-481516"}
    w.drain()
    (doc,) = w.store.documents_of_type(DocType.health_policy)
    assert doc.fields["policy_number"] == "PN-481516"


def test_a_type_answer_reads_the_file_again(make_world):
    w = make_world()
    drop(w.vault, "p.pdf", fileable(DocType.tax_invoice).data)
    w.worker.engines.models.patch = {}
    w.drain()
    (doc,) = w.store.documents_of_type(DocType.tax_invoice)
    w.actions.undo_document(doc.id)
    (held,) = w.store.items(["held"])
    w.actions.answer(held.id, "type", DocType.warranty_card.value)
    w.drain()
    assert w.store.item(held.id).state in ("filed", "asked")
    assert not w.store.documents_of_type(DocType.tax_invoice)


def test_discard_and_keep_both_for_duplicates(world):
    d = fileable(DocType.tax_invoice)
    for name in ("a.pdf", "a (1).pdf", "a (2).pdf"):
        drop(world.vault, name, d.data)
    world.drain()
    (filed,) = world.store.documents_of_type(DocType.tax_invoice)
    one, two = world.store.items(["asked"])
    world.actions.answer(one.id, "copy", "discard")
    world.actions.answer(two.id, "copy", "keep_both")
    world.drain()
    assert world.store.item(one.id).state == "discarded"
    assert world.vault.sha256(filed.rel_path) == d.sha
    assert not world.vault.exists(one.rel_path)
    docs = world.store.documents_of_type(DocType.tax_invoice)
    assert len(docs) == 2 and any(x.rel_path.endswith(" (2).pdf") for x in docs)


def test_an_undone_file_is_held_until_retry(world):
    drop(world.vault, "w.pdf", fileable(DocType.warranty_card).data)
    world.drain()
    (doc,) = world.store.documents_of_type(DocType.warranty_card)
    world.actions.undo_document(doc.id)
    world.drain()
    (held,) = world.store.items(["held"])
    assert not world.store.documents_of_type(DocType.warranty_card)
    world.actions.retry(held.id)
    world.drain()
    assert world.store.documents_of_type(DocType.warranty_card)[0].rel_path == doc.rel_path


def test_undo_item_moves_a_question_back_to_inbox(world):
    drop(world.vault, "empty.pdf", b"")
    world.drain()
    (item,) = world.store.items(["asked"])
    held = world.actions.undo_item(item.id)
    assert held.state == "held" and held.rel_path.startswith("Inbox/")


def test_an_undo_whose_name_was_taken_says_so(world, monkeypatch):
    drop(world.vault, "w.pdf", fileable(DocType.warranty_card).data)
    world.drain()
    (doc,) = world.store.documents_of_type(DocType.warranty_card)

    def taken(*args, **kwargs):
        raise FileExistsError("taken")

    monkeypatch.setattr(world.filer, "undo", taken)
    with pytest.raises(UndoError, match="already in Inbox"):
        world.actions.undo_document(doc.id)


def test_answers_to_busy_or_finished_items_are_refused(world):
    d = fileable(DocType.tax_invoice)
    drop(world.vault, "a.pdf", d.data)
    world.drain()
    (item,) = world.store.items(["filed"])
    with pytest.raises(AnswerError):
        world.actions.answer(item.id, "person", "p1")


# -- discard never deletes the only copy ----------------------------------------------------------

from household_vault.vaultroot import INBOX  # noqa: E402
from tests.conftest import World  # noqa: E402

GONE = "The other copy is no longer there. Nothing was deleted."


def copies_of(w: World, sha: str) -> list[str]:
    found = []
    for folder in w.vault.root.rglob("*"):
        rel = folder.relative_to(w.vault.root).as_posix()
        if folder.is_file() and not rel.startswith("_system") and w.vault.sha256(rel) == sha:
            found.append(rel)
    return found


def _duplicate(world: World):
    d = fileable(DocType.tax_invoice)
    drop(world.vault, "a.pdf", d.data)
    drop(world.vault, "a (1).pdf", d.data)
    world.drain()
    (filed,) = world.store.documents_of_type(DocType.tax_invoice)
    (dup,) = world.store.items(["asked"])
    return d, filed, dup


def test_a_duplicate_is_not_discarded_after_the_filed_original_was_deleted(world):
    d, filed, dup = _duplicate(world)
    world.vault.unlink(filed.rel_path)
    with pytest.raises(AnswerError, match=GONE):
        world.actions.answer(dup.id, "copy", "discard")
    assert copies_of(world, d.sha) == [dup.rel_path]
    assert world.store.item(dup.id).state == "asked"


def test_a_duplicate_is_not_discarded_after_the_filed_original_was_replaced(world):
    d, filed, dup = _duplicate(world)
    world.vault.unlink(filed.rel_path)
    world.vault.write_atomic(filed.rel_path, b"%PDF-1.4 an edited copy")
    with pytest.raises(AnswerError, match=GONE):
        world.actions.answer(dup.id, "copy", "discard")
    assert copies_of(world, d.sha) == [dup.rel_path]


def test_a_duplicate_is_discarded_while_the_filed_original_is_intact(world):
    d, filed, dup = _duplicate(world)
    world.actions.answer(dup.id, "copy", "discard")
    assert copies_of(world, d.sha) == [filed.rel_path]


def _two_in_needs_a_look(make_world):
    w = make_world(models=TruthModels(patch={"patient": "Anita Sharma"}))
    d = fileable(DocType.prescription)
    drop(w.vault, "a.pdf", d.data)
    w.drain()
    (first,) = w.store.items(["asked"])
    drop(w.vault, "a (1).pdf", d.data)
    w.drain()
    dup = next(i for i in w.store.items(["asked"]) if i.id != first.id)
    assert dup.reasons == [Reason.duplicate]
    return w, d, first, dup


def test_a_duplicate_is_not_discarded_after_its_original_was_discarded(make_world):
    w, d, first, dup = _two_in_needs_a_look(make_world)
    w.actions.answer(first.id, "discard", "")
    with pytest.raises(AnswerError, match=GONE):
        w.actions.answer(dup.id, "copy", "discard")
    assert copies_of(w, d.sha) == [dup.rel_path]


def test_a_duplicate_is_not_discarded_after_its_original_was_undone_and_removed(make_world):
    w, d, first, dup = _two_in_needs_a_look(make_world)
    held = w.actions.undo_item(first.id)
    w.vault.unlink(held.rel_path)
    with pytest.raises(AnswerError, match=GONE):
        w.actions.answer(dup.id, "copy", "discard")
    assert copies_of(w, d.sha) == [dup.rel_path]


def test_a_file_dragged_back_to_inbox_is_not_discarded_as_a_duplicate_of_its_old_self(make_world):
    w = make_world(models=TruthModels(patch={"patient": "Anita Sharma"}))
    d = fileable(DocType.prescription)
    drop(w.vault, "a.pdf", d.data)
    w.drain()
    (first,) = w.store.items(["asked"])
    w.vault.move(first.rel_path, f"{INBOX}/a.pdf")  # moved back by hand in Drive
    w.drain()
    new = next(i for i in w.store.items(["asked"]) if i.id != first.id)
    assert new.reasons == [Reason.duplicate]
    with pytest.raises(AnswerError, match=GONE):
        w.actions.answer(new.id, "copy", "discard")
    assert copies_of(w, d.sha) == [new.rel_path]


def test_a_possible_copy_is_not_discarded_after_the_filed_document_was_deleted(make_world):
    w = make_world(models=TruthModels(patch={"invoice_number": "INV-0001"}))
    first = fileable(DocType.tax_invoice)
    second = fileable(DocType.tax_invoice, variant="scan")
    drop(w.vault, "a.pdf", first.data)
    w.drain()
    drop(w.vault, "b.pdf", second.data)
    w.drain()
    (filed,) = w.store.documents_of_type(DocType.tax_invoice)
    (asked,) = w.store.items(["asked"])
    assert asked.reasons == [Reason.possible_copy]
    w.vault.unlink(filed.rel_path)
    with pytest.raises(AnswerError, match=GONE):
        w.actions.answer(asked.id, "copy", "discard")
    assert copies_of(w, second.sha) == [asked.rel_path]


def test_a_possible_copy_is_discarded_while_the_filed_document_is_intact(make_world):
    w = make_world(models=TruthModels(patch={"invoice_number": "INV-0001"}))
    drop(w.vault, "a.pdf", fileable(DocType.tax_invoice).data)
    w.drain()
    drop(w.vault, "b.pdf", fileable(DocType.tax_invoice, variant="scan").data)
    w.drain()
    (asked,) = w.store.items(["asked"])
    w.actions.answer(asked.id, "copy", "discard")
    assert w.store.item(asked.id).state == "discarded"
    assert not w.vault.exists(asked.rel_path)
    assert len(w.store.documents_of_type(DocType.tax_invoice)) == 1


# -- an answer is refused when the item changed under it -----------------------------------------


def _paused(world, monkeypatch, act):
    """Run act in a thread that stops right after the state check passed."""
    import threading

    passed, go = threading.Event(), threading.Event()
    real = type(world.actions)._answerable
    me: dict[str, threading.Thread] = {}

    def answerable(self, item_id):
        out = real(self, item_id)
        if threading.current_thread() is me.get("t"):
            passed.set()
            go.wait(10)
        return out

    monkeypatch.setattr(type(world.actions), "_answerable", answerable)
    errors: list[Exception] = []

    def run():
        try:
            act()
        except Exception as exc:
            errors.append(exc)

    t = threading.Thread(target=run)
    me["t"] = t
    t.start()
    assert passed.wait(10)
    return go, t, errors


def test_a_second_answer_does_not_revive_a_filed_item(make_world, monkeypatch):
    w = make_world(models=TruthModels(patch={"patient": "Anita Sharma"}))
    drop(w.vault, "a.pdf", fileable(DocType.prescription).data)
    w.drain()
    (item,) = w.store.items(["asked"])
    go, t, errors = _paused(w, monkeypatch, lambda: w.actions.answer(item.id, "person", "p2"))
    w.actions.answer(item.id, "person", "p2")
    w.drain()
    assert w.store.item(item.id).state == "filed"
    go.set()
    t.join(10)
    w.drain()
    assert [type(e) for e in errors] == [AnswerError]
    assert w.store.item(item.id).state == "filed"
    assert len(w.store.documents_of_type(DocType.prescription)) == 1


def test_a_second_unlock_does_not_revive_a_filed_item_or_keep_the_password(world, monkeypatch):
    d = fileable(DocType.health_policy, variant="locked")
    drop(world.vault, "policy.pdf", d.data)
    world.drain()
    (item,) = world.store.items(["asked"])
    go, t, errors = _paused(
        world, monkeypatch, lambda: world.actions.unlock(item.id, d.doc.password)
    )
    world.actions.unlock(item.id, d.doc.password)
    world.drain()
    go.set()
    t.join(10)
    world.drain()
    assert [type(e) for e in errors] == [AnswerError]
    assert world.store.item(item.id).state == "filed"
    assert world.worker.pending_passwords == {}


def test_an_answer_racing_a_discard_does_not_revive_the_item(make_world, monkeypatch):
    w = make_world(models=TruthModels(patch={"patient": "Anita Sharma"}))
    drop(w.vault, "a.pdf", fileable(DocType.prescription).data)
    w.drain()
    (item,) = w.store.items(["asked"])
    go, t, errors = _paused(w, monkeypatch, lambda: w.actions.answer(item.id, "person", "p2"))
    w.actions.answer(item.id, "discard", "")
    go.set()
    t.join(10)
    w.drain()
    assert w.store.item(item.id).state == "discarded"
    assert [type(e) for e in errors] == [AnswerError]


def test_a_failed_second_unlock_leaves_the_first_ones_password_in_place(world, monkeypatch):
    d = fileable(DocType.health_policy, variant="locked")
    drop(world.vault, "policy.pdf", d.data)
    world.drain()
    (item,) = world.store.items(["asked"])
    go, t, errors = _paused(
        world, monkeypatch, lambda: world.actions.unlock(item.id, d.doc.password)
    )
    world.actions.unlock(item.id, d.doc.password)  # lands first; its job has not run yet
    go.set()
    t.join(10)
    assert [type(e) for e in errors] == [AnswerError]
    assert world.worker.pending_passwords == {item.id: d.doc.password}
    world.drain()
    assert world.store.item(item.id).state == "filed"
    assert world.worker.pending_passwords == {}


def test_answer_many_says_which_files_were_refused_and_answers_the_rest(make_world):
    w = make_world(models=TruthModels(patch={"patient": "Anita Sharma"}))
    drop(w.vault, "a.pdf", fileable(DocType.prescription).data)
    drop(w.vault, "b.pdf", fileable(DocType.tax_invoice).data)
    w.drain()
    (asked,) = w.store.items(["asked"])
    (filed,) = w.store.items(["filed"])
    with pytest.raises(PartlyAnswered) as caught:
        w.actions.answer_many([filed.id, asked.id], "p2")
    assert list(caught.value.refused) == [filed.id]
    assert [i.id for i in caught.value.answered] == [asked.id]
    w.drain()
    assert w.store.item(asked.id).state == "filed" and w.store.item(filed.id).state == "filed"
