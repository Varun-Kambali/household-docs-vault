"""Fixtures for the search, page and reveal routes: a real app state with a few eval-v1
documents filed through the worker, a fake prompt reader, a fake embedder and a fake revealer."""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from vault_synth.household import HOUSEHOLD

from household_vault.api.app import create_app
from household_vault.app_state import AppState, build_app_state
from household_vault.reading.engines import Engines
from household_vault.reading.ollama import ModelUnavailable
from tests.conftest import EVAL_V1, _eval_docs, drop
from tests.fakes import FakeEmbedder, FakePromptReader, TruthModels, TruthPages

FILED = ("tax_invoice-1-photo", "tax_invoice-6-photo", "health_policy-1-photo")

FIND = {
    "intent": "find",
    "people": [],
    "types": [],
    "areas": [],
    "field": None,
    "date": None,
    "place": None,
    "words": "",
}


class AnyPrompt(dict):
    """A table that answers every prompt with a plain find of its own words."""

    def __missing__(self, prompt: str) -> str:
        return json.dumps({**FIND, "words": prompt})


class FakeRevealer:
    def __init__(self) -> None:
        self.paths: list[Path] = []

    def reveal(self, path: Path) -> None:
        self.paths.append(path)


@pytest.fixture
def spy_reader() -> FakePromptReader:
    return FakePromptReader(AnyPrompt())


@pytest.fixture
def fake_revealer() -> FakeRevealer:
    return FakeRevealer()


def _build(settings, tmp_path, clock, **parts) -> AppState:
    people = tmp_path / "household.json"
    people.write_text(HOUSEHOLD.model_dump_json())
    ready = settings.model_copy(update={"household_path": people, "settle_seconds": 0.0})
    return build_app_state(
        ready, engines=Engines(TruthPages(), TruthModels()), clock=clock, **parts
    )


def _file(state: AppState, doc_id: str) -> None:
    doc = next(d for d in _eval_docs() if d.doc_id == doc_id)
    drop(state.vault, doc.files[0], (EVAL_V1 / doc.files[0]).read_bytes())
    state.worker.drain()


@pytest.fixture
def search_state(settings, tmp_path, clock, spy_reader, fake_revealer) -> Iterator[AppState]:
    s = _build(
        settings,
        tmp_path,
        clock,
        embedder=FakeEmbedder(),
        prompt_reader=spy_reader,
        revealer=fake_revealer,
    )
    for doc_id in FILED:
        _file(s, doc_id)
    yield s
    s.gate.lock()
    s.store.conn.close()


@pytest.fixture
def search_client(search_state) -> TestClient:
    return TestClient(create_app(search_state, start_worker=False), base_url="http://localhost")


@pytest.fixture
def client_without_ollama(settings, tmp_path, clock, fake_revealer) -> Iterator[TestClient]:
    off = FakePromptReader(AnyPrompt(), fail=ModelUnavailable("off"))
    s = _build(settings, tmp_path, clock, prompt_reader=off, revealer=fake_revealer)
    for doc_id in FILED:
        _file(s, doc_id)
    yield TestClient(create_app(s, start_worker=False), base_url="http://localhost")
    s.gate.lock()
    s.store.conn.close()


@pytest.fixture
def filed_ids(search_state) -> list[str]:
    with search_state.store.lock:
        return [
            r[0] for r in search_state.store.conn.execute("select id from documents order by id")
        ]
