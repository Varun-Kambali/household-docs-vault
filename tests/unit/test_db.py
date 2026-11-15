from datetime import datetime, timedelta

import pytest

from household_vault.config import ConfigError
from household_vault.db import SCHEMA_VERSION, Store, connect, migrate
from household_vault.reading.lines import PageText
from tests.conftest import item_id, line, reopen, row


def test_migrate_is_idempotent(tmp_path):
    conn = connect(tmp_path / "v.db", tmp_path / "vault")
    assert migrate(conn) == SCHEMA_VERSION == migrate(conn)


def test_database_refuses_a_path_inside_the_vault(tmp_path):
    with pytest.raises(ConfigError):
        connect(tmp_path / "vault" / "v.db", tmp_path / "vault")


def test_remove_document_takes_its_people_pages_and_lines(store):
    store.add_document(
        row("d1", item_id=item_id(store)),
        [("p1", "owner")],
        [PageText(page=0, width=1, height=1, lines=[line("x")])],
    )
    store.remove_document("d1")
    assert store.document("d1") is None and store.people_of("d1") == []
    assert store.conn.execute("select count(*) from lines").fetchone()[0] == 0


def test_jobs_run_oldest_first_after_their_time(store, now):
    a = store.enqueue(item_id(store), "process", not_before=now + timedelta(minutes=1))
    b = store.enqueue(item_id(store), "process")
    assert store.claim_next(now).id == b and store.claim_next(now) is None
    assert store.claim_next(now + timedelta(minutes=2)).id == a


def test_a_job_left_running_is_found_after_a_restart(store, now):
    store.enqueue(item_id(store), "process")
    store.claim_next(now)
    assert len(Store(reopen(store)).running_jobs()) == 1


def test_requeue_and_defer(store, now):
    i = item_id(store)
    store.update_item(i, state="held")
    job = store.requeue(i)
    assert store.item(i).state == "queued" and store.claim_next(now).id == job
    store.defer(job, now + timedelta(seconds=30))
    assert store.claim_next(now) is None
    assert store.claim_next(now + timedelta(seconds=31)).attempts == 1


def test_home_owner_items_order_and_uploads(store, now):
    store.add_document(row("d2", item_id=item_id(store), owner="home"), [("home", "owner")], [])
    a = store.add_item("a" * 64, "a.pdf", "Inbox/a.pdf", now)
    up = store.add_item("b" * 64, "card.jpg", None, now, origin="upload")
    assert [x.id for x in store.items(["queued"])][-2:] == [a.id, up.id]
    assert store.item_at("Inbox/a.pdf").id == a.id and up.rel_path is None


def test_a_failed_transaction_changes_nothing(store):
    i = item_id(store)
    with pytest.raises(RuntimeError), store.transaction():
        store.requeue(i)
        store.update_item(i, state="held")
        raise RuntimeError
    assert store.item(i).state == "queued"
    assert store.conn.execute("select count(*) from jobs").fetchone()[0] == 0


def test_item_json_fields_round_trip_and_item_at_skips_finished_items(store, now):
    from household_vault.reasons import Reason

    it = store.add_item("d" * 64, "d.pdf", "Inbox/d.pdf", now)
    changed = store.update_item(
        it.id,
        state="asked",
        reasons=[Reason.duplicate],
        pending={"secret_ref": "r1"},
        overrides={"owner": "p2"},
    )
    assert changed.reasons == [Reason.duplicate] and changed.pending == {"secret_ref": "r1"}
    assert changed.overrides == {"owner": "p2"} and changed.updated_at >= it.updated_at
    assert store.item_at("Inbox/d.pdf").id == it.id
    store.update_item(it.id, state="filed")
    assert store.item_at("Inbox/d.pdf") is None
    with pytest.raises(KeyError):
        store.item(999)
    with pytest.raises(KeyError):
        store.update_item(it.id, nonsense=1)


def test_household_round_trips_and_filed_with_sha(store, now):
    assert [p.id for p in store.household().people][:2] == ["p1", "p2"]
    store.add_document(row("d3", item_id=item_id(store), sha256="e" * 64), [("p1", "owner")], [])
    assert [d.id for d in store.filed_with_sha("e" * 64)] == ["d3"]
    assert isinstance(now, datetime)
