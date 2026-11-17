import pytest

from household_vault.actions import AnswerError
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
