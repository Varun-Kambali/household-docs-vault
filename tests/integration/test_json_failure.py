"""A fill that never returns usable JSON can still be filed once the owner answers (I4)."""

from household_vault.doctypes import REQUIRED, DocType
from household_vault.reasons import Reason
from tests.conftest import drop, fileable
from tests.fakes import TruthModels


class BrokenFill(TruthModels):
    def fill(self, doc_type, images, ocr_text, sha256):
        self._gate()
        return '{"insurer": "Star Health", "policy_number": "P-1'  # cut off, as at num_predict


def test_the_owner_can_type_what_a_cut_off_read_lacks(make_world):
    w = make_world(models=BrokenFill())
    d = fileable(DocType.health_policy)
    drop(w.vault, "a.pdf", d.data)
    w.drain()
    (item,) = w.store.items(["asked"])
    assert Reason.read_failed in item.reasons
    w.actions.answer(item.id, "type", "health_policy")
    w.drain()
    item = w.store.item(item.id)
    assert Reason.read_failed not in item.reasons
    for name in sorted(REQUIRED[DocType.health_policy]):
        if item.state != "asked":
            break
        value = d.doc.fields.get(name)
        if isinstance(value, list):
            value = ", ".join(value)
        w.actions.answer(item.id, "field", str(value), field=name)
        w.drain()
        item = w.store.item(item.id)
    if item.state == "asked" and item.question["answer_kind"] == "person":
        w.actions.answer(item.id, "person", "p1")
        w.drain()
        item = w.store.item(item.id)
    assert item.state == "filed"
