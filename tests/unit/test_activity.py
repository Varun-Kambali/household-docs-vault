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
