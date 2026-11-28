"""The SQLite store: items, documents, people, page text, the job queue and the activity rows.

The database file lives outside the vault (ADR 0006), so a sync client never copies a live
database. It holds fields and line text, never a secret. Times are stored as ISO text with their
offset; job times are normalised to UTC so they compare as text.
"""

import functools
import json
import logging
import sqlite3
import threading
from collections.abc import Callable, Collection, Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal, cast

from household_vault.config import ConfigError
from household_vault.doctypes import DocType
from household_vault.people import Household
from household_vault.reading.lines import PageText
from household_vault.reasons import Reason
from household_vault.safety import is_within

SCHEMA_VERSION = 3

ItemState = Literal[
    "queued",
    "reading",
    "filing",
    "filed_pending_clear",
    "filed",
    "undoing",
    "moving",
    "asked",
    "held",
    "waiting_secrets",
    "gone",
    "discarded",
]
JobKind = Literal["process", "refile", "embed"]
Origin = Literal["inbox", "upload"]

CARD_MARK = "was_card"  # in an item's overrides: it has been read as a card front

_SCHEMA = """
create table people (id text primary key, name text not null default '');
create table items (
    id integer primary key autoincrement,
    sha256 text not null,
    original_name text not null,
    origin text not null check (origin in ('inbox', 'upload')),
    rel_path text,
    target text,
    pending text,
    kind text,
    state text not null,
    reasons text not null default '[]',
    question text,
    reading text,
    overrides text not null default '{}',
    document_id text,
    created_at text not null,
    updated_at text not null
);
create index items_state on items (state);
create index items_sha on items (sha256);
create index items_path on items (rel_path);
create table documents (
    id text primary key,
    item_id integer not null references items (id),
    doc_type text not null,
    owner text not null references people (id),
    area text not null,
    rel_path text not null,
    sha256 text not null,
    doc_date text not null,
    date_source text not null check (date_source in ('document', 'received')),
    description text not null,
    fields text not null,
    issues text not null,
    secret_ref text,
    created_at text not null
);
create index documents_sha on documents (sha256);
create index documents_type on documents (doc_type);
create table document_people (
    document_id text not null references documents (id) on delete cascade,
    person_id text not null references people (id),
    role text not null check (role in ('owner', 'linked')),
    primary key (document_id, person_id)
);
create table pages (
    document_id text not null references documents (id) on delete cascade,
    page integer not null,
    width integer not null,
    height integer not null,
    primary key (document_id, page)
);
create table lines (
    document_id text not null references documents (id) on delete cascade,
    page integer not null,
    idx integer not null,
    text text not null,
    box text not null,
    confidence real,
    primary key (document_id, page, idx)
);
create table jobs (
    id integer primary key autoincrement,
    item_id integer not null references items (id),
    kind text not null,
    state text not null,
    attempts integer not null default 0,
    not_before text,
    created_at text not null
);
create index jobs_state on jobs (state, id);
create table activity (
    id integer primary key autoincrement,
    csv_pending integer not null default 0,
    time text not null,
    item_id integer,
    step text not null,
    outcome text not null,
    file text,
    detail text not null
);
create table meta (key text primary key, value text not null);
"""


_SCHEMA_2 = """
create virtual table search_text using fts5(
    document_id unindexed, page unindexed, idx unindexed, kind unindexed, field unindexed,
    text, tokenize = 'unicode61 remove_diacritics 2'
);
create table vectors (
    id integer primary key,
    document_id text not null references documents (id) on delete cascade,
    page integer,
    first integer,
    last integer,
    model text not null,
    dims integer not null,
    vec blob not null
);
"""

_SCHEMA_3 = """
create table notes (
    document_id text primary key references documents (id) on delete cascade,
    paper text not null default '',
    login text not null default '',
    updated_at text not null
);
create table reminder_state (
    key text primary key,
    state text not null check (state in ('done', 'snoozed')),
    until text,
    at text not null
);
create table custom_reminders (
    id integer primary key,
    document_id text not null references documents (id) on delete cascade,
    due text not null,
    title text not null,
    created_at text not null
);
create table settings (key text primary key, value text not null);
"""

log = logging.getLogger(__name__)


def connect(path: Path, vault_root: Path) -> sqlite3.Connection:
    """Open (and create) the database. A path inside the vault is refused."""
    if is_within(path, vault_root):
        raise ConfigError(f"the database must live outside the vault, not at {path}")
    resolved = path.expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    # The worker thread and the API threads share one Store; the Store's lock serialises them.
    conn = sqlite3.connect(resolved, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma journal_mode = wal")
    conn.execute("pragma foreign_keys = on")
    conn.execute("pragma busy_timeout = 5000")
    return conn


def migrate(conn: sqlite3.Connection) -> int:
    """Create the tables on a new database, upgrade an older one, return the version."""
    has_meta = conn.execute("select 1 from sqlite_master where name = 'meta'").fetchone()
    if has_meta is None:
        version_row = f"insert into meta values ('schema_version', '{SCHEMA_VERSION}');"
        try:
            conn.executescript("begin;" + _SCHEMA + _SCHEMA_2 + _SCHEMA_3 + version_row + "commit;")
        except BaseException:
            if conn.in_transaction:
                conn.execute("rollback")
            raise
    # An owner of "home" is a household-wide document, so it needs a people row for the key.
    conn.execute("insert or ignore into people (id, name) values ('home', 'Home')")
    version = int(conn.execute("select value from meta where key = 'schema_version'").fetchone()[0])
    if version == 1:
        _upgrade_1_to_2(conn)
        version = 2
    if version == 2:
        _upgrade_2_to_3(conn)
        version = 3
    if version != SCHEMA_VERSION:
        raise ConfigError(f"the database has schema {version}; this app writes {SCHEMA_VERSION}")
    return version


def _upgrade_1_to_2(conn: sqlite3.Connection) -> None:
    """Add the search tables and index the documents already filed, all or nothing."""
    from household_vault.search.index import KeywordIndex

    store = Store(conn)
    with store.transaction():
        for statement in _SCHEMA_2.split(";\n"):
            if statement.strip():
                conn.execute(statement)
        KeywordIndex(store).rebuild()
        conn.execute("update meta set value = '2' where key = 'schema_version'")


def _upgrade_2_to_3(conn: sqlite3.Connection) -> None:
    """Add the notes, reminder state, custom reminder and settings tables, all or nothing."""
    store = Store(conn)
    with store.transaction():
        for statement in _SCHEMA_3.split(";\n"):
            if statement.strip():
                conn.execute(statement)
        conn.execute("update meta set value = '3' where key = 'schema_version'")


class StateChanged(Exception):
    """An item was not in any of the states the caller expected, so nothing was changed."""


@dataclass(frozen=True)
class Item:
    id: int
    sha256: str
    original_name: str
    origin: Origin
    rel_path: str | None
    target: str | None
    pending: dict[str, Any] | None
    kind: str | None
    state: ItemState
    reasons: list[Reason]
    question: dict[str, Any] | None
    reading: dict[str, Any] | None
    overrides: dict[str, Any]
    document_id: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class DocumentRow:
    id: str
    item_id: int
    doc_type: DocType
    owner: str
    area: str
    rel_path: str
    sha256: str
    doc_date: date
    date_source: Literal["document", "received"]
    description: str
    fields: dict[str, Any] = field(default_factory=dict)
    issues: dict[str, Any] = field(default_factory=dict)
    secret_ref: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now().astimezone())


@dataclass(frozen=True)
class StoredLine:
    """One stored (masked) line of a filed document."""

    page: int
    idx: int
    text: str
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True)
class Notes:
    """Where the paper original is kept and a login hint: plain text, never a secret."""

    paper: str = ""
    login: str = ""
    updated_at: datetime | None = None


ReminderMark = Literal["done", "snoozed"]


@dataclass(frozen=True)
class ReminderState:
    state: ReminderMark
    until: date | None
    at: datetime


@dataclass(frozen=True)
class CustomReminder:
    id: int
    document_id: str
    due: date
    title: str
    created_at: datetime


@dataclass(frozen=True)
class Job:
    id: int
    item_id: int
    kind: JobKind
    state: str
    attempts: int
    not_before: datetime | None


_ITEM_COLUMNS = frozenset(
    {
        "sha256",
        "original_name",
        "origin",
        "rel_path",
        "target",
        "pending",
        "kind",
        "state",
        "reasons",
        "question",
        "reading",
        "overrides",
        "document_id",
    }
)
_JSON_COLUMNS = frozenset({"pending", "reasons", "question", "reading", "overrides"})


def _dump(value: Any) -> str | None:
    return None if value is None else json.dumps(value, ensure_ascii=False, default=str)


def _load(text: str | None) -> Any:
    return None if text is None else json.loads(text)


def _utc(t: datetime) -> str:
    """A fixed-width UTC text, so two job times compare correctly as text."""
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")


def _from_utc(text: str | None) -> datetime | None:
    if text is None:
        return None
    return datetime.fromisoformat(text).replace(tzinfo=UTC).astimezone()


def _now() -> datetime:
    return datetime.now().astimezone()


def _reasons(values: list[str]) -> list[Reason]:
    """The stored reasons this version knows; one it does not know is dropped and logged."""
    known: list[Reason] = []
    for value in values:
        try:
            known.append(Reason(value))
        except ValueError:
            log.warning("dropping an unknown reason on an item: %r", value)
    return known


def _item(r: sqlite3.Row) -> Item:
    return Item(
        id=r["id"],
        sha256=r["sha256"],
        original_name=r["original_name"],
        origin=r["origin"],
        rel_path=r["rel_path"],
        target=r["target"],
        pending=_load(r["pending"]),
        kind=r["kind"],
        state=r["state"],
        reasons=_reasons(_load(r["reasons"])),
        question=_load(r["question"]),
        reading=_load(r["reading"]),
        overrides=_load(r["overrides"]),
        document_id=r["document_id"],
        created_at=datetime.fromisoformat(r["created_at"]),
        updated_at=datetime.fromisoformat(r["updated_at"]),
    )


def _document(r: sqlite3.Row) -> DocumentRow:
    return DocumentRow(
        id=r["id"],
        item_id=r["item_id"],
        doc_type=DocType(r["doc_type"]),
        owner=r["owner"],
        area=r["area"],
        rel_path=r["rel_path"],
        sha256=r["sha256"],
        doc_date=date.fromisoformat(r["doc_date"]),
        date_source=r["date_source"],
        description=r["description"],
        fields=_load(r["fields"]),
        issues=_load(r["issues"]),
        secret_ref=r["secret_ref"],
        created_at=datetime.fromisoformat(r["created_at"]),
    )


def _job(r: sqlite3.Row) -> Job:
    return Job(
        id=r["id"],
        item_id=r["item_id"],
        kind=r["kind"],
        state=r["state"],
        attempts=r["attempts"],
        not_before=_from_utc(r["not_before"]),
    )


def _marks(values: Collection[Any]) -> str:
    return ",".join("?" * len(values))


def _locked[F: Callable[..., Any]](fn: F) -> F:
    """Run a Store method while holding the Store's lock."""

    @functools.wraps(fn)
    def wrapper(self: "Store", *args: Any, **kwargs: Any) -> Any:
        with self.lock:
            return fn(self, *args, **kwargs)

    return cast(F, wrapper)


class Store:
    """Every read and write the app makes. One Store per thread: a connection is not shared."""

    def __init__(
        self, conn: sqlite3.Connection, clock: Callable[[], datetime] | None = None
    ) -> None:
        self.conn = conn
        self._clock = clock or _now
        self.lock = threading.RLock()
        self._depth = 0
        # Counts every change to the stored vectors that this Store makes, so a vector index
        # holding them in memory knows to load them again.
        self.vectors_epoch = 0

    @property
    def in_transaction(self) -> bool:
        """True while the calling thread is inside `transaction()`."""
        with self.lock:
            return self._depth > 0

    def transaction(self) -> AbstractContextManager[None]:
        return self._transaction()

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        """All or nothing. A transaction inside another one joins it."""
        with self.lock:
            yield from self._transaction_locked()

    def _transaction_locked(self) -> Iterator[None]:
        if self._depth:
            self._depth += 1
            try:
                yield
            finally:
                self._depth -= 1
            return
        self.conn.execute("begin immediate")
        self._depth = 1
        try:
            yield
        except BaseException:
            self.conn.execute("rollback")
            raise
        else:
            self.conn.execute("commit")
        finally:
            self._depth = 0

    # -- items ---------------------------------------------------------------------------------

    @_locked
    def add_item(
        self,
        sha256: str,
        name: str,
        rel_path: str | None,
        now: datetime,
        origin: Origin = "inbox",
    ) -> Item:
        stamp = now.astimezone().isoformat()
        cur = self.conn.execute(
            "insert into items (sha256, original_name, origin, rel_path, state, created_at,"
            " updated_at) values (?, ?, ?, ?, 'queued', ?, ?)",
            (sha256, name, origin, rel_path, stamp, stamp),
        )
        assert cur.lastrowid is not None
        return self.item(cur.lastrowid)

    @_locked
    def item(self, item_id: int) -> Item:
        r = self.conn.execute("select * from items where id = ?", (item_id,)).fetchone()
        if r is None:
            raise KeyError(item_id)
        return _item(r)

    @_locked
    def update_item(self, item_id: int, **changes: Any) -> Item:
        unknown = set(changes) - _ITEM_COLUMNS
        if unknown:
            raise KeyError(f"not an item field: {sorted(unknown)}")
        # Being a card is sticky: once a reading comes back as a card front, the item keeps a
        # marker in its overrides that no later answer or re-read can clear.
        current = self.item(item_id)
        new_reading = changes.get("reading")
        marked = (
            current.overrides.get(CARD_MARK)
            or (changes.get("overrides") or {}).get(CARD_MARK)
            or (isinstance(new_reading, dict) and new_reading.get("doc_type") == "card_front")
        )
        if marked:
            changes["overrides"] = {
                **(changes.get("overrides", current.overrides)),
                CARD_MARK: True,
            }
        sets, args = [], []
        for name, value in changes.items():
            if name == "reasons":
                value = [Reason(x).value for x in value]
            sets.append(f"{name} = ?")
            args.append(_dump(value) if name in _JSON_COLUMNS else value)
        sets.append("updated_at = ?")
        args.append(self._clock().astimezone().isoformat())
        cur = self.conn.execute(
            f"update items set {', '.join(sets)} where id = ?",
            (*args, item_id),
        )
        if cur.rowcount == 0:
            raise KeyError(item_id)
        return self.item(item_id)

    @_locked
    def update_item_if(
        self, item_id: int, from_states: Collection[ItemState], **changes: Any
    ) -> Item:
        """`update_item`, but only while the item is in one of `from_states`; else `StateChanged`.
        The check and the change are one step, so another thread cannot slip in between."""
        if not from_states:
            raise StateChanged(f"item {item_id}: no state allows this")
        with self.transaction():
            if self.item(item_id).state not in from_states:
                raise StateChanged(f"item {item_id} is no longer in the expected state")
            return self.update_item(item_id, **changes)

    @_locked
    def items(self, states: Collection[ItemState]) -> list[Item]:
        if not states:
            return []
        rows = self.conn.execute(
            f"select * from items where state in ({_marks(states)})"
            " order by julianday(created_at), id",
            tuple(states),
        ).fetchall()
        return [_item(r) for r in rows]

    @_locked
    def item_at(self, rel_path: str) -> Item | None:
        """The newest live item at a path. Uploads have no path, so they never match."""
        r = self.conn.execute(
            "select * from items where rel_path = ? and state not in ('gone', 'discarded',"
            " 'filed') order by id desc limit 1",
            (rel_path,),
        ).fetchone()
        return None if r is None else _item(r)

    @_locked
    def is_card_sha(self, sha256: str) -> bool:
        """True when any item, in any state, holding these bytes was read or typed as a card
        front, is marked as a card, waits for the secrets store or asks about a card number."""
        row = self.conn.execute(
            "select 1 from items where sha256 = ? and ("
            " json_extract(reading, '$.doc_type') = 'card_front'"
            " or json_extract(overrides, '$.doc_type') = 'card_front'"
            " or json_extract(overrides, '$.was_card') = 1"
            " or state = 'waiting_secrets' or reasons like '%card_unreadable%'"
            ") limit 1",
            (sha256,),
        ).fetchone()
        return row is not None

    @_locked
    def items_with_sha(self, sha256: str, states: Collection[ItemState]) -> list[Item]:
        if not states:
            return []
        rows = self.conn.execute(
            f"select * from items where sha256 = ? and state in ({_marks(states)})"
            " order by julianday(created_at), id",
            (sha256, *states),
        ).fetchall()
        return [_item(r) for r in rows]

    # -- documents -----------------------------------------------------------------------------

    @_locked
    def filed_with_sha(self, sha256: str) -> list[DocumentRow]:
        rows = self.conn.execute(
            "select * from documents where sha256 = ? order by created_at, id", (sha256,)
        ).fetchall()
        return [_document(r) for r in rows]

    @_locked
    def add_document(
        self,
        row: DocumentRow,
        people: Sequence[tuple[str, Literal["owner", "linked"]]],
        pages: Sequence[PageText],
    ) -> None:
        with self.transaction():
            self.conn.execute(
                "insert into documents (id, item_id, doc_type, owner, area, rel_path, sha256,"
                " doc_date, date_source, description, fields, issues, secret_ref, created_at)"
                " values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.id,
                    row.item_id,
                    row.doc_type.value,
                    row.owner,
                    row.area,
                    row.rel_path,
                    row.sha256,
                    row.doc_date.isoformat(),
                    row.date_source,
                    row.description,
                    _dump(row.fields),
                    _dump(row.issues),
                    row.secret_ref,
                    row.created_at.astimezone().isoformat(),
                ),
            )
            self.conn.executemany(
                "insert into document_people values (?, ?, ?)",
                [(row.id, person, role) for person, role in people],
            )
            for p in pages:
                self.conn.execute(
                    "insert into pages values (?, ?, ?, ?)", (row.id, p.page, p.width, p.height)
                )
                self.conn.executemany(
                    "insert into lines values (?, ?, ?, ?, ?, ?)",
                    [
                        (
                            row.id,
                            p.page,
                            i,
                            ln.text,
                            json.dumps([round(x, 4) for x in ln.bbox]),
                            None if ln.confidence is None else round(ln.confidence, 4),
                        )
                        for i, ln in enumerate(p.lines)
                    ],
                )

    @_locked
    def document(self, doc_id: str) -> DocumentRow | None:
        r = self.conn.execute("select * from documents where id = ?", (doc_id,)).fetchone()
        return None if r is None else _document(r)

    @_locked
    def lines_of(self, doc_id: str, page: int | None = None) -> list[StoredLine]:
        """The stored, masked lines of a document in page and line order."""
        sql = "select page, idx, text, box from lines where document_id = ?"
        args: tuple[Any, ...] = (doc_id,)
        if page is not None:
            sql += " and page = ?"
            args = (doc_id, page)
        rows = self.conn.execute(sql + " order by page, idx", args).fetchall()
        return [
            StoredLine(r["page"], r["idx"], r["text"], cast(Any, tuple(json.loads(r["box"]))))
            for r in rows
        ]

    @_locked
    def count_documents_with_secrets(self) -> int:
        """How many filed documents keep something in the secrets file."""
        row = self.conn.execute(
            "select count(*) from documents where secret_ref is not null"
        ).fetchone()
        return int(row[0])

    @_locked
    def documents_of_type(self, doc_type: DocType) -> list[DocumentRow]:
        rows = self.conn.execute(
            "select * from documents where doc_type = ? order by created_at, id",
            (doc_type.value,),
        ).fetchall()
        return [_document(r) for r in rows]

    @_locked
    def people_of(self, doc_id: str) -> list[tuple[str, str]]:
        rows = self.conn.execute(
            "select person_id, role from document_people where document_id = ?"
            " order by role desc, person_id",
            (doc_id,),
        ).fetchall()
        return [(r[0], r[1]) for r in rows]

    @_locked
    def remove_document(self, doc_id: str) -> None:
        # The foreign key removes the document's vector rows with it.
        self.conn.execute("delete from documents where id = ?", (doc_id,))
        self.vectors_epoch += 1

    # -- notes, reminders and settings ---------------------------------------------------------

    @_locked
    def notes_of(self, doc_id: str) -> Notes:
        r = self.conn.execute(
            "select paper, login, updated_at from notes where document_id = ?", (doc_id,)
        ).fetchone()
        if r is None:
            return Notes()
        return Notes(r["paper"], r["login"], datetime.fromisoformat(r["updated_at"]))

    @_locked
    def set_notes(self, doc_id: str, paper: str, login: str) -> Notes:
        now = self._clock()
        self.conn.execute(
            "insert into notes (document_id, paper, login, updated_at) values (?, ?, ?, ?)"
            " on conflict (document_id) do update set paper = excluded.paper,"
            " login = excluded.login, updated_at = excluded.updated_at",
            (doc_id, paper, login, now.isoformat()),
        )
        return Notes(paper, login, now)

    @_locked
    def reminder_states(self) -> dict[str, ReminderState]:
        rows = self.conn.execute("select key, state, until, at from reminder_state").fetchall()
        return {
            r["key"]: ReminderState(
                cast(ReminderMark, r["state"]),
                None if r["until"] is None else date.fromisoformat(r["until"]),
                datetime.fromisoformat(r["at"]),
            )
            for r in rows
        }

    @_locked
    def set_reminder_state(self, key: str, state: ReminderMark, until: date | None) -> None:
        self.conn.execute(
            "insert into reminder_state (key, state, until, at) values (?, ?, ?, ?)"
            " on conflict (key) do update set state = excluded.state, until = excluded.until,"
            " at = excluded.at",
            (key, state, None if until is None else until.isoformat(), self._clock().isoformat()),
        )

    @_locked
    def clear_reminder_state(self, key: str) -> None:
        self.conn.execute("delete from reminder_state where key = ?", (key,))

    @_locked
    def add_custom_reminder(self, doc_id: str, due: date, title: str) -> int:
        cur = self.conn.execute(
            "insert into custom_reminders (document_id, due, title, created_at)"
            " values (?, ?, ?, ?)",
            (doc_id, due.isoformat(), title, self._clock().isoformat()),
        )
        assert cur.lastrowid is not None
        return cur.lastrowid

    @_locked
    def custom_reminders(self) -> list[CustomReminder]:
        rows = self.conn.execute(
            "select id, document_id, due, title, created_at from custom_reminders order by due, id"
        ).fetchall()
        return [
            CustomReminder(
                r["id"],
                r["document_id"],
                date.fromisoformat(r["due"]),
                r["title"],
                datetime.fromisoformat(r["created_at"]),
            )
            for r in rows
        ]

    @_locked
    def remove_custom_reminder(self, reminder_id: int) -> None:
        self.conn.execute("delete from custom_reminders where id = ?", (reminder_id,))

    @_locked
    def setting(self, key: str) -> str | None:
        r = self.conn.execute("select value from settings where key = ?", (key,)).fetchone()
        return None if r is None else r["value"]

    @_locked
    def set_setting(self, key: str, value: str) -> None:
        self.conn.execute(
            "insert into settings (key, value) values (?, ?)"
            " on conflict (key) do update set value = excluded.value",
            (key, value),
        )

    # -- household -----------------------------------------------------------------------------

    @_locked
    def set_household(self, h: Household) -> None:
        with self.transaction():
            for person in h.people:
                self.conn.execute(
                    "insert into people (id, name) values (?, ?)"
                    " on conflict (id) do update set name = excluded.name",
                    (person.id, person.name),
                )
            self.conn.execute(
                "insert into meta values ('household', ?)"
                " on conflict (key) do update set value = excluded.value",
                (h.model_dump_json(),),
            )

    @_locked
    def household(self) -> Household:
        r = self.conn.execute("select value from meta where key = 'household'").fetchone()
        return Household() if r is None else Household.model_validate_json(r[0])

    # -- jobs ----------------------------------------------------------------------------------

    @_locked
    def enqueue(self, item_id: int, kind: JobKind, not_before: datetime | None = None) -> int:
        cur = self.conn.execute(
            "insert into jobs (item_id, kind, state, not_before, created_at)"
            " values (?, ?, 'queued', ?, ?)",
            (item_id, kind, None if not_before is None else _utc(not_before), _utc(self._clock())),
        )
        assert cur.lastrowid is not None
        return cur.lastrowid

    @_locked
    def requeue(
        self,
        item_id: int,
        kind: JobKind = "process",
        not_before: datetime | None = None,
        from_states: Collection[ItemState] | None = None,
    ) -> int:
        """Put an item back in the queue: its state and a new job, together. With `from_states`
        the state change only happens while the item is in one of them (checked in the same
        transaction), and `StateChanged` is raised, with nothing changed, when it is not."""
        with self.transaction():
            if from_states is None:
                self.update_item(item_id, state="queued")
            else:
                self.update_item_if(item_id, from_states, state="queued")
            return self.enqueue(item_id, kind, not_before)

    @_locked
    def claim_next(self, now: datetime) -> Job | None:
        with self.transaction():
            r = self.conn.execute(
                "select * from jobs where state = 'queued' and (not_before is null"
                " or not_before <= ?) order by id limit 1",
                (_utc(now),),
            ).fetchone()
            if r is None:
                return None
            self.conn.execute("update jobs set state = 'running' where id = ?", (r["id"],))
            return _job(self.conn.execute("select * from jobs where id = ?", (r["id"],)).fetchone())

    @_locked
    def defer(self, job_id: int, not_before: datetime) -> None:
        cur = self.conn.execute(
            "update jobs set state = 'queued', attempts = attempts + 1, not_before = ?"
            " where id = ? and state = 'running'",
            (_utc(not_before), job_id),
        )
        if cur.rowcount == 0:
            raise KeyError(f"job {job_id} is not running")

    @_locked
    def finish(self, job_id: int, state: Literal["done", "failed"]) -> None:
        cur = self.conn.execute(
            "update jobs set state = ? where id = ? and state = 'running'", (state, job_id)
        )
        if cur.rowcount == 0:
            raise KeyError(f"job {job_id} is not running")

    @_locked
    def has_open_job(self, item_id: int, kind: JobKind) -> bool:
        row = self.conn.execute(
            "select 1 from jobs where item_id = ? and kind = ? and state in ('queued', 'running')"
            " limit 1",
            (item_id, kind),
        ).fetchone()
        return row is not None

    @_locked
    def running_jobs(self) -> list[Job]:
        rows = self.conn.execute("select * from jobs where state = 'running' order by id")
        return [_job(r) for r in rows.fetchall()]
