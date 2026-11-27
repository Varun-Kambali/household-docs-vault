"""GET /v1/secrets/status: whether the secrets file exists and whether it is open."""

import pytest
from fastapi.testclient import TestClient
from vault_synth.household import HOUSEHOLD

from household_vault.api.app import create_app
from household_vault.app_state import build_app_state
from household_vault.reading.engines import Engines
from tests.conftest import MASTER_PASSWORD
from tests.fakes import TruthModels, TruthPages


@pytest.fixture
def state(settings, tmp_path, clock):
    people = tmp_path / "household.json"
    people.write_text(HOUSEHOLD.model_dump_json())
    ready = settings.model_copy(update={"household_path": people, "settle_seconds": 0.0})
    s = build_app_state(ready, engines=Engines(TruthPages(), TruthModels()), clock=clock)
    yield s
    s.gate.lock()
    s.store.conn.close()


@pytest.fixture
def client(state):
    return TestClient(create_app(state, start_worker=False), base_url="http://localhost")


def test_secrets_status_says_whether_the_file_exists_and_is_unlocked(client, state):
    assert client.get("/v1/secrets/status").json() == {"exists": False, "unlocked": False}
    created = client.post("/v1/secrets/create", json={"master_password": MASTER_PASSWORD})
    assert created.status_code == 200
    assert client.get("/v1/secrets/status").json() == {"exists": True, "unlocked": True}
    state.gate.lock()
    assert client.get("/v1/secrets/status").json() == {"exists": True, "unlocked": False}
    client.post("/v1/secrets/unlock", json={"master_password": MASTER_PASSWORD})
    assert client.get("/v1/secrets/status").json() == {"exists": True, "unlocked": True}


def test_secrets_status_carries_nothing_else(client):
    reply = client.get("/v1/secrets/status")
    assert set(reply.json()) == {"exists", "unlocked"}
    assert MASTER_PASSWORD not in reply.text


def test_secrets_status_is_behind_the_same_origin_and_host_checks(state):
    app = create_app(state, start_worker=False)
    stranger = TestClient(app, base_url="http://evil.example")
    assert stranger.get("/v1/secrets/status").status_code == 400
