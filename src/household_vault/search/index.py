"""The keyword index: SQLite full-text search over a document's stored lines and fields.

It holds only what the database already holds: the masked line text and the stored fields, so
it adds no new secret. Fields are indexed as `<label> <value>`, which keeps an identifier the
lines masked (an IMEI, a policy number) findable.
"""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from household_vault.db import Store
from household_vault.schemas import SCHEMAS
from household_vault.schemas._coerce import field_kind
from household_vault.search.vocab import FIELD_LABELS

_WORD = re.compile(r"\w")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


@dataclass(frozen=True)
class KeywordHit:
    document_id: str
    page: int | None
    idx: int | None
    kind: Literal["line", "field"]
    field: str | None
    score: float


def _amount(value: Any) -> str:
    try:
        return f"{Decimal(str(value)).normalize():f}"
    except InvalidOperation:
        return str(value)


def _date_forms(value: Any) -> str:
    try:
        d = date.fromisoformat(str(value))
    except ValueError:
        return str(value)
    return f"{d.isoformat()} {d.day} {d.strftime('%b %Y')}"


def _value_text(kind: str, value: Any) -> str:
    if isinstance(value, list):
        return " ".join(_value_text(kind, v) for v in value if v is not None)
    if kind == "date":
        return _date_forms(value)
    if kind == "amount":
        return _amount(value)
    return str(value)


def _match_query(text: str, prefix_last: bool) -> str | None:
    """Every word quoted, so FTS5 operators are plain words. None when no word has a letter
    or a digit in it."""
    words = [w for w in _CONTROL.sub(" ", text).split() if _WORD.search(w)]
    if not words:
        return None
    quoted = ['"' + w.replace('"', '""') + '"' for w in words]
    if prefix_last:
        quoted[-1] += "*"
    return " ".join(quoted)


class KeywordIndex:
    def __init__(self, store: Store) -> None:
        self.store = store

    def add(self, doc_id: str) -> None:
        """Index a document's lines and fields, replacing what was there. Call it inside the
        transaction that adds the document."""
        with self.store.lock, self.store.transaction():
            doc = self.store.document(doc_id)
            if doc is None:
                return
            self.remove(doc_id)
            insert = "insert into search_text values (?, ?, ?, ?, ?, ?)"
            for ln in self.store.lines_of(doc_id):
                self.store.conn.execute(insert, (doc_id, ln.page, ln.idx, "line", None, ln.text))
            schema = SCHEMAS.get(doc.doc_type)
            for name, value in doc.fields.items():
                if value is None or value == [] or value == "":
                    continue
                kind = (
                    field_kind(schema, name) if schema and name in schema.model_fields else "text"
                )
                label = FIELD_LABELS.get(name, name.replace("_", " "))
                text = f"{label} {_value_text(kind, value)}"
                self.store.conn.execute(insert, (doc_id, None, None, "field", name, text))

    def remove(self, doc_id: str) -> None:
        with self.store.lock:
            self.store.conn.execute("delete from search_text where document_id = ?", (doc_id,))

    def rebuild(self) -> int:
        """Index every document again from the tables. Returns how many documents."""
        with self.store.lock, self.store.transaction():
            self.store.conn.execute("delete from search_text")
            ids = [r[0] for r in self.store.conn.execute("select id from documents order by id")]
            for doc_id in ids:
                self.add(doc_id)
            return len(ids)

    def search(self, text: str, limit: int = 50, prefix_last: bool = True) -> list[KeywordHit]:
        query = _match_query(text, prefix_last)
        if query is None:
            return []
        with self.store.lock:
            rows = self.store.conn.execute(
                "select document_id, page, idx, kind, field, bm25(search_text) as rank"
                " from search_text where search_text match ? order by rank limit ?",
                (query, limit),
            ).fetchall()
        return [KeywordHit(r[0], r[1], r[2], r[3], r[4], -float(r[5])) for r in rows]
