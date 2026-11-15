"""The activity log: one database row and one CSV line per step, for people to read.

The CSV sits in the vault (`_system/log/<YYYY-MM>.csv`) so it can be opened on a phone. Cells
are made formula-safe because document text can reach them. An entry never carries a field
value or a secret; `outcome` is a short code and `detail` the sentence a person reads.
"""

import csv
import io
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from household_vault.db import Store
from household_vault.vaultroot import LOGS, VaultRoot

CSV_HEADER = ("time", "step", "outcome", "file", "detail")
_FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


class Step(StrEnum):
    noticed = "noticed"
    checked = "checked"
    read = "read"
    filed = "filed"
    needs_a_look = "needs_a_look"
    waiting = "waiting"
    undone = "undone"
    answered = "answered"
    discarded = "discarded"
    kept_both = "kept_both"
    unlocked = "unlocked"
    secrets = "secrets"
    gone = "gone"
    retried = "retried"
    error = "error"


@dataclass(frozen=True)
class ActivityEntry:
    id: int
    time: datetime
    item_id: int | None
    step: Step
    outcome: str
    file: str | None
    detail: str


def csv_cell(text: str) -> str:
    """One line of plain text that a spreadsheet will not run as a formula."""
    flat = text.replace("\r", " ").replace("\n", " ") if text else text
    # A leading CR was turned into a space above, so test the original start too.
    if text.startswith(_FORMULA_STARTS) or flat.startswith(_FORMULA_STARTS):
        return "'" + flat
    return flat


class Activity:
    def __init__(self, store: Store, vault: VaultRoot, clock: Callable[[], datetime]) -> None:
        self.store = store
        self.vault = vault
        self.clock = clock

    def record(
        self,
        item_id: int | None,
        step: Step,
        outcome: str,
        detail: str = "",
        file: str | None = None,
    ) -> ActivityEntry:
        when = self.clock().astimezone()
        cur = self.store.conn.execute(
            "insert into activity (time, item_id, step, outcome, file, detail)"
            " values (?, ?, ?, ?, ?, ?)",
            (when.isoformat(timespec="seconds"), item_id, step.value, outcome, file, detail),
        )
        assert cur.lastrowid is not None
        self._append_csv(when, step, outcome, file, detail)
        return ActivityEntry(
            id=cur.lastrowid,
            time=datetime.fromisoformat(when.isoformat(timespec="seconds")),
            item_id=item_id,
            step=step,
            outcome=outcome,
            file=file,
            detail=detail,
        )

    def _append_csv(
        self, when: datetime, step: Step, outcome: str, file: str | None, detail: str
    ) -> None:
        rel = f"{LOGS}/{when:%Y-%m}.csv"
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        if not self.vault.exists(rel):
            self.vault.mkdirs(LOGS)
            writer.writerow(CSV_HEADER)
        writer.writerow(
            [
                when.isoformat(timespec="seconds"),
                step.value,
                csv_cell(outcome),
                csv_cell(file or ""),
                csv_cell(detail),
            ]
        )
        self.vault.append_text(rel, buf.getvalue())

    def entries(self, limit: int = 100, before_id: int | None = None) -> list[ActivityEntry]:
        """Newest first. Pass the last id of a page as `before_id` to get the next page."""
        rows = self.store.conn.execute(
            "select * from activity where (? is null or id < ?) order by id desc limit ?",
            (before_id, before_id, limit),
        ).fetchall()
        return [
            ActivityEntry(
                id=r["id"],
                time=datetime.fromisoformat(r["time"]),
                item_id=r["item_id"],
                step=Step(r["step"]),
                outcome=r["outcome"],
                file=r["file"],
                detail=r["detail"],
            )
            for r in rows
        ]
