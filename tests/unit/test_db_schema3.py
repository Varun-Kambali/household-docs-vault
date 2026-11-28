"""Schema 3: notes, reminder state, custom reminders and settings."""

import sqlite3
from datetime import date

import pytest

from household_vault.db import SCHEMA_VERSION, Store, connect, migrate
from household_vault.leakscan import scan_outputs
from tests.conftest import item_id, row

NEW_TABLES = ("notes", "reminder_state", "custom_reminders", "settings")


def _filed(store: Store, doc_id: str = "d1") -> str:
    store.add_document(row(doc_id, item_id=item_id(store)), [("p1", "owner")], [])
    return doc_id


def _tables(conn) -> set[str]:
    return {r[0] for r in conn.execute("select name from sqlite_master where type = 'table'")}


@pytest.fixture
def v2_database(tmp_path, store):
    """A schema-2 database that holds one document: the new tables dropped, version put back."""
    _filed(store)
    for table in NEW_TABLES:
        store.conn.execute(f"drop table {table}")
    store.conn.execute("update meta set value = '2' where key = 'schema_version'")
    return store.conn


def test_a_new_database_is_at_schema_3_with_the_new_tables(store):
    assert SCHEMA_VERSION == 3
    assert set(NEW_TABLES) <= _tables(store.conn)
    assert (
        store.conn.execute("select value from meta where key='schema_version'").fetchone()[0] == "3"
    )


def test_a_schema_2_database_upgrades_to_3_and_keeps_its_documents(v2_database):
    assert migrate(v2_database) == 3
    assert set(NEW_TABLES) <= _tables(v2_database)
    assert v2_database.execute("select id from documents").fetchall()[0][0] == "d1"
    assert migrate(v2_database) == 3


def test_a_failed_upgrade_leaves_the_schema_2_database_as_it_was(v2_database, monkeypatch):
    from household_vault import db

    monkeypatch.setattr(db, "_SCHEMA_3", db._SCHEMA_3 + "\ncreate table broken (;")
    with pytest.raises(sqlite3.Error):
        migrate(v2_database)
    assert (
        v2_database.execute("select value from meta where key='schema_version'").fetchone()[0]
        == "2"
    )
    assert not set(NEW_TABLES) & _tables(v2_database)


def test_a_schema_1_database_walks_through_to_3(tmp_path):
    from tests.schema_v1 import SCHEMA_1

    conn = connect(tmp_path / "old" / "v.db", tmp_path / "vault")
    conn.executescript(
        "begin;" + SCHEMA_1 + "insert into meta values ('schema_version', '1');commit;"
    )
    assert migrate(conn) == 3
    assert set(NEW_TABLES) <= _tables(conn)


def test_notes_start_empty_and_are_kept_per_document(store):
    d1, d2 = _filed(store, "d1"), _filed(store, "d2")
    assert store.notes_of(d1).paper == "" and store.notes_of(d1).login == ""
    saved = store.set_notes(d1, "Steel cupboard, top shelf", "Account is the mobile number")
    assert (saved.paper, saved.login) == (
        "Steel cupboard, top shelf",
        "Account is the mobile number",
    )
    assert store.notes_of(d1) == saved
    assert store.notes_of(d2).paper == ""
    store.set_notes(d1, "Moved", "")
    assert store.notes_of(d1).paper == "Moved" and store.notes_of(d1).login == ""


def test_notes_go_with_their_document(store):
    d1 = _filed(store)
    store.set_notes(d1, "somewhere", "")
    store.remove_document(d1)
    assert store.conn.execute("select count(*) from notes").fetchone()[0] == 0


def test_reminder_state_is_set_changed_and_cleared(store):
    assert store.reminder_states() == {}
    store.set_reminder_state("k1", "done", None)
    store.set_reminder_state("k2", "snoozed", date(2027, 1, 5))
    states = store.reminder_states()
    assert states["k1"].state == "done" and states["k1"].until is None
    assert states["k2"].state == "snoozed" and states["k2"].until == date(2027, 1, 5)
    store.set_reminder_state("k2", "done", None)
    assert (
        store.reminder_states()["k2"].state == "done"
        and store.reminder_states()["k2"].until is None
    )
    store.clear_reminder_state("k1")
    assert set(store.reminder_states()) == {"k2"}
    store.clear_reminder_state("nothing")  # no error


def test_reminder_state_refuses_an_unknown_state(store):
    with pytest.raises(sqlite3.Error):
        store.set_reminder_state("k", "deleted", None)  # type: ignore[arg-type]


def test_custom_reminders_are_added_listed_removed_and_go_with_the_document(store):
    d1 = _filed(store)
    a = store.add_custom_reminder(d1, date(2027, 3, 1), "Ask the agent about renewal")
    b = store.add_custom_reminder(d1, date(2027, 2, 1), "Collect the original")
    got = store.custom_reminders()
    assert [c.id for c in got] == [b, a]  # soonest first
    assert got[1].document_id == d1 and got[1].due == date(2027, 3, 1)
    assert got[1].title == "Ask the agent about renewal"
    store.remove_custom_reminder(b)
    assert [c.id for c in store.custom_reminders()] == [a]
    store.remove_custom_reminder(999)  # no error
    store.remove_document(d1)
    assert store.custom_reminders() == []


def test_settings_round_trip(store):
    assert store.setting("lead") is None
    store.set_setting("lead", "30")
    store.set_setting("lead", "45")
    assert store.setting("lead") == "45"


def test_the_leak_scan_covers_the_new_tables(store, tmp_path, vault):
    d1 = _filed(store)
    card = "4111 1111 1111 1111"
    store.set_notes(d1, f"card {card}", "")
    store.set_reminder_state("k", "done", None)
    store.add_custom_reminder(d1, date(2027, 1, 1), f"pay {card}")
    store.set_setting("x", f"n {card}")
    (tmp_path / "logs").mkdir(exist_ok=True)
    db_path = tmp_path / "db" / "vault.db"
    hits = scan_outputs(vault, db_path, tmp_path / "logs")
    for table, column in (
        ("notes", "paper"),
        ("custom_reminders", "title"),
        ("settings", "value"),
    ):
        assert any(f"vault.db:{table}.{column}" in h for h in hits), (table, hits)
