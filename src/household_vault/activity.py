"""The activity log: one database row and one CSV line per step, for people to read.

The CSV sits in the vault (`_system/log/<YYYY-MM>.csv`) so it can be opened on a phone. Cells
are made formula-safe because document text can reach them. An entry never carries a field
value or a secret; `outcome` is a short code and `detail` the sentence a person reads.
"""

import csv
import io
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from household_vault.db import Store
from household_vault.schemas.parse import mask_card_numbers
from household_vault.vaultroot import LOGS, VaultPathError, VaultRoot

log = logging.getLogger(__name__)

CSV_HEADER = ("time", "step", "outcome", "file", "detail")
_FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r", "\uff1d", "\uff0b", "\uff0d", "\uff20")
_BLANKS = " \t\r\n\u3000\u00a0"


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
    """One line of plain text that a spreadsheet will not run as a formula.

    A formula can hide behind leading blanks, and the fullwidth signs count in some sheets.
    """
    flat = text.replace("\r", " ").replace("\n", " ")
    if text.lstrip(_BLANKS).startswith(_FORMULA_STARTS) or text.startswith(("\t", "\r")):
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
        stamp = when.isoformat(timespec="seconds")
        detail = mask_card_numbers(detail)
        file = None if file is None else mask_card_numbers(file)
        with self.store.lock:
            cur = self.store.conn.execute(
                "insert into activity (time, item_id, step, outcome, file, detail, csv_pending)"
                " values (?, ?, ?, ?, ?, ?, 1)",
                (stamp, item_id, step.value, outcome, file, detail),
            )
            assert cur.lastrowid is not None
            self.backfill_csv()
        return ActivityEntry(
            id=cur.lastrowid,
            time=datetime.fromisoformat(stamp),
            item_id=item_id,
            step=step,
            outcome=outcome,
            file=file,
            detail=detail,
        )

    def backfill_csv(self) -> int:
        """Write every row not yet in the CSV, oldest first. Returns how many were written.

        A write that fails leaves the row pending for the next call; the warning names no text.
        """
        written = 0
        with self.store.lock:
            pending = self.store.conn.execute(
                "select * from activity where csv_pending = 1 order by id"
            ).fetchall()
            for r in pending:
                try:
                    self._append_csv(
                        datetime.fromisoformat(r["time"]),
                        Step(r["step"]),
                        r["outcome"],
                        r["file"],
                        r["detail"],
                    )
                except (OSError, VaultPathError) as exc:
                    log.warning(
                        "activity log row %s not written to the CSV: %s",
                        r["id"],
                        type(exc).__name__,
                    )
                    break
                self.store.conn.execute(
                    "update activity set csv_pending = 0 where id = ?", (r["id"],)
                )
                written += 1
        return written

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
