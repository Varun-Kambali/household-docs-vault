"""Card photos and numbers on the routes the owner's answers and copies take (range re-review)."""

import json

import pytest
from fastapi.testclient import TestClient
from vault_synth.household import HOUSEHOLD

from household_vault.actions import AnswerError
from household_vault.api.app import create_app
from household_vault.app_state import build_app_state
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
