"""The keyword index: SQLite full-text search over a document's stored lines and fields.

It holds only what the database already holds: the masked line text and the stored fields, so
it adds no new secret. Fields are indexed as `<label> <value>`, which keeps an identifier the
lines masked (an IMEI, a policy number) findable.
"""

import re
from collections.abc import Collection
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


def _last_fours(value: Any) -> str:
    """The last four digits of each identifier of 8 or more digits, as a token of their own, so
    a prompt masked down to its last four ("•••• 7518") still finds the document. Only the
    index text carries them; the vector summary does not."""
    out = []
    for v in value if isinstance(value, list) else [value]:
        digits = re.sub(r"\D", "", str(v)) if v is not None else ""
        if len(digits) >= 8:
            out.append(digits[-4:])
    return "".join(f" {d}" for d in out)


# Words that carry no search meaning of their own. Any-word matching drops them. If every word
# of the prompt is one of them, the match has no words and finds nothing.
_FILLER_TEXT = (
    "a an the of for to in on at by and or is are was were be do does did my our me i we it its "
    "this that what which who whom whose when where how show find get give tell list all any"
)
_FILLER = frozenset(_FILLER_TEXT.split())


def _match_query(text: str, prefix_last: bool, any_word: bool = False) -> str | None:
    """Every word quoted, so FTS5 operators are plain words. None when no word has a letter
    or a digit in it. With `any_word` a row needs only one of the words (filler words dropped);
    otherwise it needs all of them."""
    words = [w for w in _CONTROL.sub(" ", text).split() if _WORD.search(w)]
    if any_word:
        kept = [w for w in words if w.lower().strip("'\u2019?.,!") not in _FILLER]
        words = kept
    if not words:
        return None
    quoted = ['"' + w.replace('"', '""') + '"' for w in words]
    if prefix_last:
        quoted[-1] += "*"
    return (" OR " if any_word else " ").join(quoted)


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
                if kind == "identifier":
                    text += _last_fours(value)
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

    def search(
        self,
        text: str,
        limit: int = 50,
        prefix_last: bool = True,
        only: Collection[str] | None = None,
        any_word: bool = False,
    ) -> list[KeywordHit]:
        """Matches best first. `only` limits them to those document ids (None means all).

        By default a hit holds every word in one line or field. With `any_word` a hit holds
        at least one of them and the hits are grouped by document, the document that scores
        best (the sum of its hits' BM25) first, so words spread over a document's lines and
        fields still find it."""
        query = _match_query(text, prefix_last, any_word)
        if query is None or (only is not None and not only):
            return []
        if any_word:
            return self._search_any(query, limit, only)
        sql = (
            "select document_id, page, idx, kind, field, bm25(search_text) as rank"
            " from search_text where search_text match ?"
        )
        args: list[object] = [query]
        if only is not None:
            ids = list(only)
            sql += f" and document_id in ({','.join('?' * len(ids))})"
            args += ids
        with self.store.lock:
            rows = self.store.conn.execute(
                sql + " order by rank limit ?", (*args, limit)
            ).fetchall()
        return [KeywordHit(r[0], r[1], r[2], r[3], r[4], -float(r[5])) for r in rows]

    def _search_any(self, query: str, limit: int, only: Collection[str] | None) -> list[KeywordHit]:
        sql = (
            "select document_id, page, idx, kind, field, bm25(search_text) as rank"
            " from search_text where search_text match ?"
        )
        args: list[object] = [query]
        if only is not None:
            ids = list(only)
            sql += f" and document_id in ({','.join('?' * len(ids))})"
            args += ids
        with self.store.lock:
            rows = self.store.conn.execute(sql + " order by rank", args).fetchall()
        total: dict[str, float] = {}
        for r in rows:
            total[r[0]] = total.get(r[0], 0.0) - float(r[5])
        order = {d: n for n, d in enumerate(sorted(total, key=lambda d: (-total[d], d)))}
        rows.sort(key=lambda r: (order[r[0]], float(r[5])))
        return [KeywordHit(r[0], r[1], r[2], r[3], r[4], -float(r[5])) for r in rows[:limit]]
