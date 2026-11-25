"""The built web app, served by the API: the app CSP, the fallback to the app for its own paths,
and no fallback for the API's."""

import pytest
from fastapi.testclient import TestClient
from vault_synth.household import HOUSEHOLD

from household_vault.api.app import create_app
from household_vault.app_state import build_app_state
from household_vault.reading.engines import Engines
from tests.fakes import TruthModels, TruthPages

CSP = (
    "default-src 'self'; img-src 'self' blob:; style-src 'self'; script-src 'self'; "
    "connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
    "form-action 'self'"
)


@pytest.fixture
def dist(tmp_path):
    folder = tmp_path / "dist"
    (folder / "assets").mkdir(parents=True)
    (folder / "index.html").write_text("<!doctype html><title>Vault</title><div id=root></div>")
    (folder / "assets" / "app-abc123.js").write_text("export {}")
    (folder / "assets" / "app-abc123.css").write_text("body{}")
    (folder / "favicon.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    secret = tmp_path / "outside.txt"
    secret.write_text("not for the web")
    return folder


@pytest.fixture
def client_with_dist(settings, tmp_path, clock, dist):
    people = tmp_path / "household.json"
    people.write_text(HOUSEHOLD.model_dump_json())
    ready = settings.model_copy(update={"household_path": people, "settle_seconds": 0.0})
    state = build_app_state(ready, engines=Engines(TruthPages(), TruthModels()), clock=clock)
    yield TestClient(
        create_app(state, start_worker=False, web_dist=dist), base_url="http://localhost"
    )
    state.gate.lock()
    state.store.conn.close()


def test_the_app_is_served_with_a_strict_csp(client_with_dist):
    response = client_with_dist.get("/")
    assert response.status_code == 200
    assert response.headers["content-security-policy"] == CSP
    assert "<title>Vault</title>" in response.text


def test_app_paths_fall_back_to_the_app_but_api_paths_do_not(client_with_dist):
    assert client_with_dist.get("/inbox").status_code == 200
    assert client_with_dist.get("/doc/12").text.startswith("<!doctype html>")
    assert client_with_dist.get("/area/insurance").status_code == 200
    assert client_with_dist.get("/v1/nothing").status_code == 404
    assert (
        client_with_dist.get("/v1/nothing").headers["content-type"].startswith("application/json")
    )
    assert client_with_dist.get("/healthz").json()["status"] == "ok"
    assert client_with_dist.get("/healthz/x").status_code == 404


def test_built_files_are_served_with_their_types_and_the_csp(client_with_dist):
    js = client_with_dist.get("/assets/app-abc123.js")
    assert js.status_code == 200
    assert "javascript" in js.headers["content-type"]
    assert js.headers["content-security-policy"] == CSP
    assert "immutable" in js.headers["cache-control"]
    assert "text/css" in client_with_dist.get("/assets/app-abc123.css").headers["content-type"]
    assert client_with_dist.get("/favicon.svg").status_code == 200


def test_a_missing_file_is_a_404_not_the_app(client_with_dist):
    assert client_with_dist.get("/assets/gone.js").status_code == 404
    assert client_with_dist.get("/nothing.png").status_code == 404


def test_the_app_page_is_never_cached(client_with_dist):
    assert client_with_dist.get("/inbox").headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "path", ["/../outside.txt", "/%2e%2e/outside.txt", "/assets/../../outside.txt", "//etc/passwd"]
)
def test_paths_cannot_leave_the_built_folder(client_with_dist, path):
    response = client_with_dist.get(path)
    assert "not for the web" not in response.text
    assert "root:" not in response.text


def test_only_get_and_head_reach_the_app(client_with_dist):
    assert client_with_dist.post("/inbox").status_code == 405
    assert client_with_dist.head("/inbox").status_code == 200


def test_without_a_build_the_api_runs_as_before(state_no_dist):
    assert state_no_dist.get("/").status_code == 404
    assert state_no_dist.get("/healthz").status_code == 200


@pytest.fixture
def state_no_dist(settings, tmp_path, clock, tmp_path_factory):
    people = tmp_path / "household.json"
    people.write_text(HOUSEHOLD.model_dump_json())
    ready = settings.model_copy(update={"household_path": people, "settle_seconds": 0.0})
    state = build_app_state(ready, engines=Engines(TruthPages(), TruthModels()), clock=clock)
    missing = tmp_path_factory.mktemp("empty") / "dist"
    yield TestClient(
        create_app(state, start_worker=False, web_dist=missing), base_url="http://localhost"
    )
    state.gate.lock()
    state.store.conn.close()


def test_the_web_apps_areas_match_the_vaults_areas_in_order():
    """web/src/app/areas.ts lists the sidebar's twelve areas; it must follow `Area` and the
    labels the search vocabulary uses (sentence case)."""
    import re
    from pathlib import Path

    from household_vault.doctypes import Area
    from household_vault.search.vocab import AREA_LABELS

    source = (Path(__file__).parents[3] / "web" / "src" / "app" / "areas.ts").read_text()
    listed = re.findall(r"id: '(\w+)', label: '([^']+)'", source)
    assert [a for a, _ in listed] == [a.value for a in Area]
    assert [label for _, label in listed] == [AREA_LABELS[a].capitalize() for a in Area]


def test_default_dist_follows_the_environment_and_needs_a_built_page(dist, tmp_path, monkeypatch):
    from household_vault.api.web import default_dist

    monkeypatch.setenv("VAULT_WEB_DIST", str(dist))
    assert default_dist() == dist
    monkeypatch.setenv("VAULT_WEB_DIST", str(tmp_path / "nothing"))
    assert default_dist() is None


def test_create_app_serves_the_app_only_when_given_a_build(
    settings, tmp_path, clock, dist, monkeypatch
):
    """A build lying in the working tree must not change the API a test builds."""
    monkeypatch.setenv("VAULT_WEB_DIST", str(dist))
    people = tmp_path / "household.json"
    people.write_text(HOUSEHOLD.model_dump_json())
    ready = settings.model_copy(update={"household_path": people, "settle_seconds": 0.0})
    state = build_app_state(ready, engines=Engines(TruthPages(), TruthModels()), clock=clock)
    try:
        client = TestClient(create_app(state, start_worker=False), base_url="http://localhost")
        assert client.get("/inbox").status_code == 404
    finally:
        state.gate.lock()
        state.store.conn.close()
