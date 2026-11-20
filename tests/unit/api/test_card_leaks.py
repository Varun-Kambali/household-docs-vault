"""Card photos and numbers on the routes the owner's answers and copies take (range re-review)."""

import json

import pytest
from fastapi.testclient import TestClient
from vault_synth.household import HOUSEHOLD

from household_vault.actions import AnswerError
from household_vault.api.app import create_app
from household_vault.app_state import build_app_state
from household_vault.doctypes import DocType
from household_vault.reading.engines import Engines, VisionPageReader
from tests.conftest import drop
from tests.fakes import FakeModels, FakeOcr

NUMBER = "4111 1111 1111 1111"
CARD_FILL = {
    "bank": "Deccan Trust Bank",
    "number": NUMBER.replace(" ", ""),
    "holder": "Anita Sharma",
}


@pytest.fixture
def make_state(settings, tmp_path, clock):
    made = []

    def make(ocr_text, type_, fill):
        people = tmp_path / "household.json"
        people.write_text(HOUSEHOLD.model_dump_json())
        ready = settings.model_copy(update={"household_path": people, "settle_seconds": 0.0})
        models = FakeModels(type_, json.dumps(fill))
        s = build_app_state(
            ready, engines=Engines(VisionPageReader(FakeOcr(text=ocr_text)), models), clock=clock
        )
        made.append(s)
        return s

    yield make
    for s in made:
        s.gate.lock()
        s.store.conn.close()


def client_of(s):
    return TestClient(create_app(s, start_worker=False), base_url="http://localhost")


def test_a_typed_full_number_is_refused_as_the_last_four_digits(make_state, photo):
    s = make_state(
        "Welcome Ravi Kumar Rao",
        "card_welcome_letter",
        {"bank": "Deccan Trust Bank", "holder": "Ravi Kumar Rao"},
    )
    drop(s.vault, "letter.jpg", photo)
    s.worker.drain()
    (item,) = s.store.items(["asked"])
    assert "last four digits of the card" in item.question["text"]
    with pytest.raises(AnswerError, match="last four digits"):
        s.actions.answer(item.id, "field", NUMBER, field="last4")
    s.actions.answer(item.id, "field", "1111", field="last4")
    assert s.store.item(item.id).overrides["fields"]["last4"] == "1111"


def test_an_asked_card_cannot_be_retyped_as_another_document(make_state, photo):
    s = make_state(f"{NUMBER} Anita Sharma", "card_front", CARD_FILL)
    drop(s.vault, "card.jpg", photo)
    s.worker.drain()
    (item,) = s.store.items(["asked"])
    c = client_of(s)
    assert c.get(f"/v1/items/{item.id}/file").status_code == 423
    r = c.post(f"/v1/needs-a-look/{item.id}/answer", json={"kind": "type", "value": "tax_invoice"})
    assert r.status_code == 409 and "bank card" in r.json()["detail"]
    assert c.get(f"/v1/items/{item.id}/file").status_code == 423
    s.worker.drain()
    assert s.store.item(item.id).rel_path == "Inbox/card.jpg"
    assert s.store.documents_of_type(DocType.tax_invoice) == []
    ok = c.post(
        f"/v1/needs-a-look/{item.id}/answer", json={"kind": "type", "value": "card_statement"}
    )
    assert ok.status_code == 200  # another card-area type is allowed


def test_the_item_file_is_refused_for_a_stored_card_whatever_the_override(make_state, photo):
    s = make_state(f"{NUMBER} Anita Sharma", "card_front", CARD_FILL)
    drop(s.vault, "card.jpg", photo)
    s.worker.drain()
    (item,) = s.store.items(["asked"])
    s.store.update_item(item.id, overrides={"doc_type": "tax_invoice"})
    assert client_of(s).get(f"/v1/items/{item.id}/file").status_code == 423


def test_a_copy_of_a_waiting_card_photo_stays_in_inbox_and_is_not_served(make_state, photo):
    s = make_state(f"{NUMBER} Anita Sharma", "card_front", CARD_FILL)
    drop(s.vault, "card.jpg", photo)
    drop(s.vault, "card (1).jpg", photo)
    s.worker.drain()
    items = s.store.items(["asked", "waiting_secrets", "held"])
    assert len(items) == 2
    c = client_of(s)
    for item in items:
        assert c.get(f"/v1/items/{item.id}/file").status_code == 423
        assert item.rel_path.startswith("Inbox/")
    assert s.vault.list_dir("Needs a look") == []
