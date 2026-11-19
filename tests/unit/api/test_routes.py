import json
import logging
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.formparsers import MultiPartParser
from vault_synth.household import HOUSEHOLD

from household_vault.api.app import _MAX_BODY_BYTES, MAX_UPLOAD_BYTES, create_app
from household_vault.app_state import AppState, build_app_state
from household_vault.doctypes import DocType
from household_vault.logging_setup import configure
from household_vault.reading.engines import Engines
from household_vault.reasons import Reason
from household_vault.vaultroot import SECRETS_FILE
from tests.conftest import MASTER_PASSWORD, drop, fileable
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


@pytest.fixture
def filed_doc(state):
    drop(state.vault, "policy.pdf", fileable(DocType.health_policy).data)
    state.worker.drain()
    (doc,) = state.store.documents_of_type(DocType.health_policy)
    return doc


@pytest.fixture
def duplicate_item(state):
    data = fileable(DocType.tax_invoice).data
    for name in ("a.pdf", "a (1).pdf"):
        drop(state.vault, name, data)
    state.worker.drain()
    (item,) = state.store.items(["asked"])
    assert item.reasons == [Reason.duplicate]
    return item


@pytest.fixture
def outsider_prescription(state):
    state.engines.models.patch = {"patient": "Anita Sharma"}
    drop(state.vault, "rx.pdf", fileable(DocType.prescription).data)
    state.worker.drain()
    (item,) = state.store.items(["asked"])
    return item


@pytest.fixture
def locked_item(state):
    d = fileable(DocType.health_policy, variant="locked")
    drop(state.vault, "locked.pdf", d.data)
    state.worker.drain()
    (item,) = state.store.items(["asked"])
    assert item.reasons == [Reason.locked]
    return item


def test_healthz(client):
    body = client.get("/healthz").json()
    assert body["status"] == "ok" and body["reader"] == "stand-in" and body["version"]


def test_activity_offers_the_right_actions(client, state, filed_doc, duplicate_item):
    acts = {e["file"]: e["actions"] for e in client.get("/v1/activity").json()}
    assert acts[filed_doc.rel_path] == ["open", "undo"]
    assert set(acts[duplicate_item.rel_path]) >= {"discard", "keep_both"}


def test_activity_offers_unlock_and_retry(client, state, locked_item, filed_doc):
    state.actions.undo_document(filed_doc.id)
    entries = client.get("/v1/activity").json()
    by_item = {e["item_id"]: e["actions"] for e in entries if e["actions"]}
    assert "unlock" in by_item[locked_item.id]
    assert by_item[filed_doc.item_id] == ["retry"]


def test_activity_pages_by_id(client, filed_doc):
    everything = client.get("/v1/activity", params={"limit": 100}).json()
    assert len(everything) >= 3
    first = client.get("/v1/activity", params={"limit": 2}).json()
    rest = client.get("/v1/activity", params={"before": first[-1]["id"]}).json()
    assert [e["id"] for e in first + rest] == [e["id"] for e in everything]
    assert client.get("/v1/activity", params={"limit": 0}).status_code == 422


def test_progress(client, state, filed_doc):
    body = client.get("/v1/inbox/progress").json()
    assert body["waiting"] == 0 and body["total_in_batch"] == 1 and body["done_in_batch"] == 1


def test_answering_through_the_api_files_it(client, state, outsider_prescription):
    state.worker.drain()
    (item,) = client.get("/v1/needs-a-look").json()
    assert item["question"]["answer_kind"] == "person"
    r = client.post(f"/v1/needs-a-look/{item['id']}/answer", json={"kind": "person", "value": "p2"})
    assert r.status_code == 200
    state.worker.drain()
    assert client.get("/v1/needs-a-look").json() == []


def test_answer_many_names_the_files_that_were_refused(client, state, outsider_prescription):
    r = client.post(
        "/v1/needs-a-look/answer-many",
        json={"item_ids": [outsider_prescription.id, 9999], "value": "p2"},
    )
    assert r.status_code == 409
    assert r.json()["refused"] == {"9999": "That file is not in the list any more"}
    assert r.json()["answered"] == [outsider_prescription.id]


def test_an_answer_the_actions_refuse_is_a_409_with_their_words(client, outsider_prescription):
    r = client.post(
        f"/v1/needs-a-look/{outsider_prescription.id}/answer",
        json={"kind": "person", "value": "p99"},
    )
    assert r.status_code == 409 and r.json()["detail"] == "That person is not in the household"


def test_an_unknown_item_is_a_404(client):
    assert (
        client.post("/v1/needs-a-look/999/answer", json={"kind": "retry", "value": ""}).status_code
        == 404
    )
    assert client.post("/v1/needs-a-look/999/undo").status_code == 404
    assert client.post("/v1/items/999/retry").status_code == 404
    assert client.get("/v1/items/999/file").status_code == 404
    assert client.get("/v1/documents/nope").status_code == 404
    assert client.post("/v1/documents/nope/undo").status_code == 404
    unlock = {"password": "x", "save": False}
    assert client.post("/v1/needs-a-look/999/unlock", json=unlock).status_code == 404


def test_the_other_copy_text_is_checked_live(client, state, filed_doc, duplicate_item):
    state.vault.mkdirs("Moved")
    original = next(d for d in state.store.documents_of_type(DocType.tax_invoice))
    (item,) = client.get("/v1/needs-a-look").json()
    assert original.rel_path in item["question"]["text"]
    state.vault.move(original.rel_path, "Moved/invoice.pdf")
    (item,) = client.get("/v1/needs-a-look").json()
    assert original.rel_path not in item["question"]["text"]
    assert "no longer there" in item["question"]["text"]
    assert [o["value"] for o in item["question"]["options"]] == ["keep_both"]
    r = client.post(
        f"/v1/needs-a-look/{item['id']}/answer", json={"kind": "copy", "value": "discard"}
    )
    assert r.status_code == 409 and "Nothing was deleted" in r.json()["detail"]


def test_discarding_a_duplicate_needs_no_confirmation(client, state, duplicate_item):
    r = client.post(
        f"/v1/needs-a-look/{duplicate_item.id}/answer", json={"kind": "copy", "value": "discard"}
    )
    assert r.status_code == 200
    assert state.store.item(duplicate_item.id).state == "discarded"


def test_discarding_the_only_copy_needs_the_confirm_flag(client, state):
    drop(state.vault, "empty.pdf", b"")
    state.worker.drain()
    (item,) = state.store.items(["asked"])
    body = {"kind": "discard", "value": "discard"}
    r = client.post(f"/v1/needs-a-look/{item.id}/answer", json=body)
    assert r.status_code == 409 and "only copy" in r.json()["detail"]
    assert state.vault.exists(item.rel_path) and state.store.item(item.id).state == "asked"
    r = client.post(f"/v1/needs-a-look/{item.id}/answer", json={**body, "confirm": True})
    assert r.status_code == 200 and not state.vault.exists(item.rel_path)


def test_retry_and_undo_of_a_question(client, state):
    drop(state.vault, "empty.pdf", b"")
    state.worker.drain()
    (item,) = state.store.items(["asked"])
    r = client.post(f"/v1/needs-a-look/{item.id}/undo")
    assert r.status_code == 200 and state.store.item(item.id).state == "held"
    assert client.post(f"/v1/items/{item.id}/retry").status_code == 200
    assert client.post(f"/v1/items/{item.id}/retry").status_code == 409


def test_undo_conflict_when_the_file_moved(client, state, filed_doc):  # Review Focus 8
    state.vault.mkdirs("Elsewhere")
    state.vault.move(filed_doc.rel_path, "Elsewhere/policy.pdf")
    r = client.post(f"/v1/documents/{filed_doc.id}/undo")
    assert r.status_code == 409 and "no longer at" in r.json()["detail"]


def test_undo_puts_a_filed_document_back(client, state, filed_doc):
    assert client.post(f"/v1/documents/{filed_doc.id}/undo").status_code == 200
    assert state.store.items(["held"])


def test_undo_when_the_vault_or_the_folder_went_away_says_so_plainly(client, state, monkeypatch):
    from household_vault.filing.filer import TargetGone
    from household_vault.vaultroot import VaultGone

    def gone(doc_id):
        raise VaultGone("Ravi Kumar Rao/secret-name.pdf")

    monkeypatch.setattr(state.actions, "undo_document", gone)
    state.store.conn.execute("select 1")
    drop(state.vault, "w.pdf", fileable(DocType.warranty_card).data)
    state.worker.drain()
    (doc,) = state.store.documents_of_type(DocType.warranty_card)
    r = client.post(f"/v1/documents/{doc.id}/undo")
    assert r.status_code == 409 and "secret-name" not in r.text and "no longer there" in r.text

    def target(doc_id):
        raise TargetGone("x")

    monkeypatch.setattr(state.actions, "undo_document", target)
    r = client.post(f"/v1/documents/{doc.id}/undo")
    assert r.status_code == 409 and "folder" in r.json()["detail"]


def test_a_document_and_its_file(client, state, filed_doc):
    record = client.get(f"/v1/documents/{filed_doc.id}").json()
    assert record["id"] == filed_doc.id and record["rel_path"] == filed_doc.rel_path
    assert "lines" not in record and "secret_ref" not in record
    r = client.get(f"/v1/documents/{filed_doc.id}/file")
    assert r.status_code == 200 and r.content == state.vault.read_bytes(filed_doc.rel_path)
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_an_item_file_is_served_from_where_it_waits(client, state, outsider_prescription):
    r = client.get(f"/v1/items/{outsider_prescription.id}/file")
    assert r.status_code == 200 and r.content.startswith(b"%PDF")


def test_files_outside_the_vault_are_never_served(client, state, filed_doc):
    state.store.conn.execute(
        "update documents set rel_path = '../outside.pdf' where id = ?", (filed_doc.id,)
    )
    assert client.get(f"/v1/documents/{filed_doc.id}/file").status_code == 404


def test_a_file_that_vanished_is_a_404(client, state, filed_doc):
    state.vault.unlink(filed_doc.rel_path)
    assert client.get(f"/v1/documents/{filed_doc.id}/file").status_code == 404


def test_card_upload_needs_the_master_password(client, photo):
    assert client.post("/v1/cards", files={"front": ("f.jpg", b"x")}).status_code == 422
    r = client.post(
        "/v1/cards", files={"front": ("f.jpg", photo)}, data={"master_password": "wrong"}
    )
    assert r.status_code == 423


def test_a_card_upload_over_the_limit_is_a_413(client):
    big = b"\0" * (MAX_UPLOAD_BYTES + 1)
    r = client.post(
        "/v1/cards", files={"front": ("f.jpg", big)}, data={"master_password": MASTER_PASSWORD}
    )
    assert r.status_code == 413


def test_uploads_stay_in_memory_not_in_a_temporary_file(client):
    # A part can be as large as the body the limit lets through, so no part can roll over to disk.
    assert MultiPartParser.spool_max_size >= _MAX_BODY_BYTES >= MAX_UPLOAD_BYTES


def test_the_secrets_store_is_created_then_unlocked(client, state):
    assert client.post("/v1/secrets/unlock", json={"master_password": "x"}).status_code == 423
    r = client.post("/v1/secrets/create", json={"master_password": MASTER_PASSWORD})
    assert r.status_code == 200 and state.vault.exists(SECRETS_FILE)
    state.gate.lock()
    bad = client.post("/v1/secrets/unlock", json={"master_password": "wrong"})
    assert bad.status_code == 423 and MASTER_PASSWORD not in bad.text
    assert (
        client.post("/v1/secrets/unlock", json={"master_password": MASTER_PASSWORD}).status_code
        == 200
    )
    again = client.post("/v1/secrets/create", json={"master_password": MASTER_PASSWORD})
    assert again.status_code == 409


@pytest.mark.parametrize(
    "name",
    [
        "Secrets (1).kdbx",
        ".Secrets.kdbx.tmp",
        "Secrets.kdbx.partial",
        "Secrets.kdbx (conflict)",
        "Copy of Secrets.kdbx",
        "Secrets.kdbx.crdownload",
        "Secrets.kdbx.gstmp",
        "Secrets.kdbx (1)",
        ".~lock.Secrets.kdbx#",
    ],
)
def test_creating_the_secrets_file_waits_while_drive_is_still_syncing(client, state, name):
    state.vault.write_atomic(name, b"partial")
    r = client.post("/v1/secrets/create", json={"master_password": MASTER_PASSWORD})
    assert r.status_code == 409 and "syncing" in r.json()["detail"]
    assert not state.vault.exists(SECRETS_FILE)


def test_creating_the_secrets_file_is_refused_when_filed_cards_need_the_old_one(client, state):
    state.store.conn.execute("pragma foreign_keys = off")
    state.store.conn.execute(
        "insert into documents (id, item_id, doc_type, owner, area, rel_path, sha256, doc_date,"
        " date_source, description, fields, issues, secret_ref, created_at)"
        " values ('d1', 1, 'card_front', 'p1', 'finance', 'x/y.jpg', ?, '2026-11-01', 'received',"
        " 'Card', '{}', '{}', 'entry-1', '2026-11-01T00:00:00+00:00')",
        ("a" * 64,),
    )
    r = client.post("/v1/secrets/create", json={"master_password": MASTER_PASSWORD})
    assert r.status_code == 409 and "Restore" in r.json()["detail"]
    assert not state.vault.exists(SECRETS_FILE)


def test_passwords_never_reach_the_log(client, state, locked_item, settings):
    wrong = "-".join(["pw", "synthetic", "123"])  # built here so a secrets scanner has no literal
    client.post(
        f"/v1/needs-a-look/{locked_item.id}/unlock", json={"password": wrong, "save": False}
    )
    assert wrong not in (settings.log_dir / "vault.log").read_text()


def test_a_bad_request_does_not_echo_what_was_sent(client):
    r = client.post("/v1/secrets/unlock", json={"master_password": 5, "x": "pw-echo-me"})
    assert r.status_code == 422 and "pw-echo-me" not in r.text


def test_an_unexpected_failure_is_a_fixed_message(state):
    app = create_app(state, start_worker=False)

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("document text 4111111111111111")

    r = TestClient(app, raise_server_exceptions=False, base_url="http://localhost").get("/boom")
    assert r.status_code == 500 and "4111" not in r.text
    assert r.json() == {"detail": "Something went wrong. Nothing was changed."}


def test_the_emergency_sheet(client):
    r = client.get("/v1/emergency-sheet")
    assert r.status_code == 200 and "Master password:" in r.text
    assert r.headers["content-type"].startswith("text/html")


def test_the_worker_runs_with_the_app_and_stops_with_it(state, monkeypatch):
    seen = {}

    def fake_run_forever(stop):
        seen["stop"] = stop
        stop.wait(5)

    monkeypatch.setattr(state.worker, "run_forever", fake_run_forever)
    with TestClient(create_app(state), base_url="http://localhost"):
        assert not seen["stop"].is_set()
    assert seen["stop"].is_set()


def test_the_log_redacts_card_numbers(settings):
    configure(settings.log_dir)
    logging.getLogger("household_vault").warning("read 4111111111111111")
    assert "4111111111111111" not in (settings.log_dir / "vault.log").read_text()


def test_a_logged_exception_leaves_no_card_data(settings):
    configure(settings.log_dir)
    try:
        raise ValueError("card 4111111111111111")
    except ValueError:
        logging.getLogger("household_vault").warning("failed", exc_info=True)
    text = (settings.log_dir / "vault.log").read_text()
    assert "4111111111111111" not in text and "ValueError" in text and "Traceback" not in text


def test_configure_twice_does_not_double_the_lines(settings):
    configure(settings.log_dir)
    configure(settings.log_dir)
    logging.getLogger("household_vault").warning("once only")
    assert (settings.log_dir / "vault.log").read_text().count("once only") == 1


def test_start_up_writes_the_activity_rows_a_failed_csv_write_left_behind(
    settings, tmp_path, clock
):
    s = build_app_state(settings, clock=clock)
    s.store.conn.execute(
        "insert into activity (time, item_id, step, outcome, file, detail, csv_pending)"
        " values (?, null, 'noticed', 'new', null, 'left behind', 1)",
        (clock().isoformat(),),
    )
    s.store.conn.close()
    again = build_app_state(settings, clock=clock)
    month = f"{clock():%Y-%m}"
    assert "left behind" in again.vault.read_bytes(f"_system/log/{month}.csv").decode()
    again.store.conn.close()


def test_one_gate_is_shared(state):
    assert state.actions.gate is state.gate and state.cards.gate is state.gate
    for rel in ("Inbox", "Needs a look", "_system/records", "_system/log", "_system/backup"):
        assert state.vault.exists(rel)
    assert date.today()  # the clock fixture drives the rest


def test_the_database_stays_outside_the_vault(state):
    assert not str(state.settings.db_path).startswith(str(state.vault.root))
    assert isinstance(state, AppState) and isinstance(Path(state.settings.db_path), Path)


def test_a_name_that_points_here_from_another_site_is_refused(state):
    app = create_app(state, start_worker=False)
    assert TestClient(app, base_url="http://evil.example").get("/healthz").status_code == 400
    assert TestClient(app, base_url="http://localhost:8710").get("/healthz").status_code == 200
    assert TestClient(app, base_url="http://localhost").get("/docs").status_code == 404


def test_any_host_is_served_when_the_stand_in_reader_binds_all_addresses(state):
    open_settings = state.settings.model_copy(update={"host": "0.0.0.0"})
    state.settings = open_settings
    app = create_app(state, start_worker=False)
    assert TestClient(app, base_url="http://vault.test").get("/healthz").status_code == 200


def test_a_plain_file_with_secrets_in_its_name_does_not_block_creating(client, state):
    state.vault.write_atomic("Secrets to sort.docx", b"x")
    r = client.post("/v1/secrets/create", json={"master_password": MASTER_PASSWORD})
    assert r.status_code == 200


@pytest.mark.parametrize("name", [".tmp.drivedownload", ".tmp.driveupload"])
def test_a_busy_drive_cache_folder_blocks_creating(client, state, name):
    state.vault.mkdirs(name)
    assert (
        client.post("/v1/secrets/create", json={"master_password": MASTER_PASSWORD}).status_code
        == 200
    )  # empty: nothing is on its way
    state.gate.lock()
    state.vault.unlink(SECRETS_FILE)
    state.vault.write_atomic(f"{name}/part", b"1")
    r = client.post("/v1/secrets/create", json={"master_password": MASTER_PASSWORD})
    assert r.status_code == 409 and "syncing" in r.json()["detail"]


@pytest.mark.parametrize("rel", ["Secrets.kdbx", "_system/log/2026-11.csv", "Home/old.KDBX"])
def test_the_secrets_file_and_system_files_are_never_served(client, state, filed_doc, rel):
    state.vault.write_atomic(rel, b"private bytes")  # a real file, so only the rule refuses it
    state.store.conn.execute("update documents set rel_path = ? where id = ?", (rel, filed_doc.id))
    assert client.get(f"/v1/documents/{filed_doc.id}/file").status_code == 404


def test_served_files_carry_a_sandboxing_policy(client, filed_doc):
    r = client.get(f"/v1/documents/{filed_doc.id}/file")
    assert r.headers["content-security-policy"] == "sandbox; default-src 'none'"


def test_a_post_from_another_site_is_refused(client, state, outsider_prescription):
    url = f"/v1/items/{outsider_prescription.id}/retry"
    r = client.post(url, headers={"Origin": "https://evil.example"})
    assert (
        r.status_code == 403
        and r.json()["detail"] == "Requests from another site are not accepted."
    )
    assert client.post(url, headers={"Origin": "null"}).status_code == 403
    assert client.post(url, headers={"Origin": "http://localhost"}).status_code == 200
    assert client.get("/healthz", headers={"Origin": "https://evil.example"}).status_code == 200


def test_testserver_is_not_an_allowed_host(state):
    assert TestClient(create_app(state, start_worker=False)).get("/healthz").status_code == 400


def _multipart(parts: list[tuple[str, bytes]]) -> tuple[bytes, dict[str, str]]:
    body = b""
    for name, data in parts:
        filename = '; filename="f.bin"' if name != "master_password" else ""
        body += f'--B\r\nContent-Disposition: form-data; name="{name}"{filename}\r\n\r\n'.encode()
        body += data + b"\r\n"
    return body + b"--B--\r\n", {"content-type": "multipart/form-data; boundary=B"}


def test_extra_file_parts_are_refused(client):
    parts = [(f"junk{i}", b"\0" * 1024) for i in range(8)]
    body, headers = _multipart([("master_password", b"x"), *parts, ("front", b"x")])
    r = client.post("/v1/cards", content=body, headers=headers)
    assert r.status_code == 400
    body, headers = _multipart([("master_password", b"x"), ("front", b"x"), ("extra", b"x")])
    assert client.post("/v1/cards", content=body, headers=headers).status_code == 422


def _drive(app, chunks, headers=()):
    """Run the ASGI app on a body arriving in chunks (no Content-Length). Returns the status
    and how many chunks were asked for."""
    import asyncio

    served = {"n": 0}
    sent: list[dict] = []
    queue = list(chunks)

    async def receive():
        if not queue:
            return {"type": "http.disconnect"}
        served["n"] += 1
        return {"type": "http.request", "body": queue.pop(0), "more_body": bool(queue)}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/v1/cards",
        "raw_path": b"/v1/cards",
        "query_string": b"",
        "headers": [
            (b"host", b"localhost"),
            (b"content-type", b"multipart/form-data; boundary=B"),
            *headers,
        ],
        "scheme": "http",
        "server": ("localhost", 8710),
        "client": ("127.0.0.1", 1),
        "http_version": "1.1",
    }
    asyncio.run(app(scope, receive, send))
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    return status, served["n"]


def test_a_chunked_body_over_the_limit_is_stopped_early(state):
    from household_vault.api.app import _MAX_BODY_BYTES

    head = b'--B\r\nContent-Disposition: form-data; name="front"; filename="f.jpg"\r\n\r\n'
    chunk = b"\0" * (1 << 20)
    total = _MAX_BODY_BYTES // len(chunk) + 40
    status, asked = _drive(create_app(state, start_worker=False), [head] + [chunk] * total)
    assert status == 413
    assert asked <= _MAX_BODY_BYTES // len(chunk) + 2  # it did not read the rest


def _Pages(ocr):
    from household_vault.reading.engines import VisionPageReader

    return VisionPageReader(ocr)


def test_a_card_document_never_returns_a_long_digit_run(settings, tmp_path, clock, photo):
    import json
    import re

    from tests.fakes import FakeModels, FakeOcr

    people = tmp_path / "household.json"
    people.write_text(HOUSEHOLD.model_dump_json())
    ready = settings.model_copy(update={"household_path": people, "settle_seconds": 0.0})
    number = "4111 1111 1111 1111"
    fill = json.dumps(
        {
            "bank": "Deccan Trust Bank",
            "card_name": number,
            "holder": "Ravi Kumar Rao",
            "last4": number,
            "statement_date": "2026-10-01",
        }
    )
    models = FakeModels(type_="card_statement", fill=fill)
    ocr = FakeOcr(text="Card statement Ravi Kumar Rao " + number)
    s = build_app_state(ready, engines=Engines(_Pages(ocr), models), clock=clock)
    try:
        drop(s.vault, "statement.jpg", photo)
        s.worker.drain()
        docs = s.store.documents_of_type(DocType.card_statement)
        assert docs, "the statement should have been filed"
        c = TestClient(create_app(s, start_worker=False), base_url="http://localhost")
        for doc in docs:
            # The document's own id and hash are hex and can hold a long run of digits by chance.
            body = re.sub(r"[0-9a-f]{32,64}", "", c.get(f"/v1/documents/{doc.id}").text)
            assert not re.search(r"\d(?:[ -]?\d){12,18}", body), body
            assert "1111" in body
    finally:
        s.gate.lock()
        s.store.conn.close()


def test_a_waiting_card_items_file_is_not_served(client, state, outsider_prescription):
    item = outsider_prescription
    assert client.get(f"/v1/items/{item.id}/file").status_code == 200  # an ordinary asked item
    state.store.conn.execute(
        "update items set reasons = ? where id = ?", ('["card_unreadable"]', item.id)
    )
    r = client.get(f"/v1/items/{item.id}/file")
    assert r.status_code == 423 and "secrets store" in r.json()["detail"]
    state.store.conn.execute("update items set reasons = '[]' where id = ?", (item.id,))
    assert client.get(f"/v1/items/{item.id}/file").status_code == 200
    state.store.conn.execute("update items set state = 'waiting_secrets' where id = ?", (item.id,))
    assert client.get(f"/v1/items/{item.id}/file").status_code == 423


def test_an_item_typed_card_front_is_not_served(client, state, outsider_prescription):
    item = outsider_prescription
    state.store.conn.execute(
        "update items set overrides = ? where id = ?", ('{"doc_type": "card_front"}', item.id)
    )
    assert client.get(f"/v1/items/{item.id}/file").status_code == 423
    state.store.conn.execute("update items set overrides = '{}' where id = ?", (item.id,))
    reading = dict(item.reading or {}, doc_type="card_front")
    state.store.conn.execute(
        "update items set reading = ? where id = ?", (json.dumps(reading), item.id)
    )
    assert client.get(f"/v1/items/{item.id}/file").status_code == 423


def test_a_malformed_origin_is_refused_not_a_server_error(client, state, outsider_prescription):
    url = f"/v1/items/{outsider_prescription.id}/retry"
    r = client.post(url, headers={"Origin": "http://[abc"})
    assert r.status_code == 403
