from datetime import datetime

from household_vault.activity import Step, csv_cell
from tests.conftest import csv_rows


def test_activity_writes_the_database_and_one_csv_per_month(activity, vault, clock):
    clock.set(datetime(2026, 11, 30, 23, 59).astimezone())
    activity.record(None, Step.filed, "filed", "Health policy", "Ravi Kumar Rao/Insurance/x.pdf")
    clock.set(datetime(2026, 12, 1, 0, 1).astimezone())
    activity.record(None, Step.read, "read")
    for month in ("2026-11", "2026-12"):
        rows = csv_rows(vault, f"_system/log/{month}.csv")
        assert rows[0] == ["time", "step", "outcome", "file", "detail"] and len(rows) == 2
    assert [e.step for e in activity.entries()] == [Step.read, Step.filed]


def test_csv_cells_cannot_start_a_formula(activity, vault, clock):  # Review Focus 10
    clock.set(datetime(2026, 11, 20, 10, 0).astimezone())
    activity.record(None, Step.read, "read", '=HYPERLINK("http://x")\nsecond line', "+1.pdf")
    _header, cells = csv_rows(vault, "_system/log/2026-11.csv")
    assert cells[3] == "'+1.pdf" and cells[4].startswith("'=HYPERLINK") and "\n" not in cells[4]


def test_csv_cell_covers_every_formula_start():
    for start in ("=", "+", "-", "@", "\t", "\r"):
        assert csv_cell(f"{start}x").startswith("'")
    assert csv_cell("plain") == "plain" and csv_cell("") == ""
    assert csv_cell("a\r\nb") == "a  b"


def test_entries_page_newest_first_and_keep_the_item(activity, store, clock):
    i = store.add_item("a" * 64, "a.pdf", "Inbox/a.pdf", clock()).id
    ids = [activity.record(i, Step.noticed, "ok").id for _ in range(3)]
    assert [e.id for e in activity.entries(limit=2)] == ids[::-1][:2]
    assert [e.id for e in activity.entries(before_id=ids[1])] == [ids[0]]
    assert activity.entries()[0].item_id == i


def test_a_second_entry_in_a_month_adds_no_second_header(activity, vault, clock):
    activity.record(None, Step.noticed, "ok")
    activity.record(None, Step.checked, "ok")
    assert len(csv_rows(vault, f"_system/log/{clock():%Y-%m}.csv")) == 3


def test_csv_cell_neutralises_hidden_and_fullwidth_formulas():
    fullwidth = [chr(c) + "x" for c in (0xFF1D, 0xFF0B, 0xFF0D, 0xFF20)]
    for text in (" =1+1", "  \t-2", "\u3000+3", *fullwidth):
        assert csv_cell(text).startswith("'"), text
    assert csv_cell("  plain") == "  plain"


def test_a_failed_csv_write_leaves_the_row_pending_then_backfills(
    activity, vault, clock, monkeypatch
):
    from household_vault.vaultroot import VaultRoot

    real = VaultRoot.append_text
    calls = {"n": 0}

    def flaky(self, rel, text):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("disk went away")
        real(self, rel, text)

    monkeypatch.setattr(VaultRoot, "append_text", flaky)
    first = activity.record(None, Step.noticed, "ok", "first")
    assert first.detail == "first"
    assert (
        activity.store.conn.execute(
            "select csv_pending from activity where id = ?", (first.id,)
        ).fetchone()[0]
        == 1
    )
    activity.record(None, Step.checked, "ok", "second")
    rows = csv_rows(vault, f"_system/log/{clock():%Y-%m}.csv")
    assert [r[4] for r in rows[1:]] == ["first", "second"]
    assert activity.backfill_csv() == 0


def test_a_card_number_in_detail_or_file_is_masked(activity, vault, clock):
    e = activity.record(
        None, Step.read, "ok", "card 4111 1111 1111 1111 seen", "4111111111111111.pdf"
    )
    assert "4111 1111 1111 1111" not in e.detail and "1111" in e.detail
    assert "4111111111111111" not in (e.file or "")
    rows = csv_rows(vault, f"_system/log/{clock():%Y-%m}.csv")
    assert "4111 1111 1111 1111" not in rows[1][4] and "4111111111111111" not in rows[1][3]
    stored = activity.entries()[0]
    assert "4111 1111" not in stored.detail


def test_a_stalled_csv_write_does_not_block_the_store(activity, store, vault, clock, monkeypatch):
    import threading

    from household_vault.vaultroot import VaultRoot

    real = VaultRoot.append_text
    started, release = threading.Event(), threading.Event()

    def slow(self, rel, text):
        started.set()
        release.wait(10)
        real(self, rel, text)

    monkeypatch.setattr(VaultRoot, "append_text", slow)
    t = threading.Thread(target=lambda: activity.record(None, Step.noticed, "ok", "first"))
    t.start()
    assert started.wait(5)
    done = threading.Event()

    def other() -> None:
        store.add_item("f" * 64, "f.pdf", None, clock(), origin="upload")
        activity.entries()
        done.set()

    o = threading.Thread(target=other)
    o.start()
    assert done.wait(3), "a Store call was blocked by the CSV write"
    release.set()
    t.join()
    o.join()
    rows = csv_rows(vault, f"_system/log/{clock():%Y-%m}.csv")
    assert [r[4] for r in rows[1:]] == ["first"]


def test_a_rolled_back_transaction_never_reaches_the_csv(activity, store, vault, clock):
    import pytest

    with pytest.raises(RuntimeError), store.transaction():
        activity.record(None, Step.noticed, "ok", "rolled back")
        raise RuntimeError
    assert not vault.exists(f"_system/log/{clock():%Y-%m}.csv")
    activity.record(None, Step.checked, "ok", "kept")
    rows = csv_rows(vault, f"_system/log/{clock():%Y-%m}.csv")
    assert [r[4] for r in rows[1:]] == ["kept"]


def test_a_committed_transaction_is_written_by_the_next_record(activity, store, vault, clock):
    with store.transaction():
        activity.record(None, Step.noticed, "ok", "inside")
    assert not vault.exists(f"_system/log/{clock():%Y-%m}.csv")
    assert activity.backfill_csv() == 1
    assert len(csv_rows(vault, f"_system/log/{clock():%Y-%m}.csv")) == 2
