"""Retrieval: filters on the stored fields, keyword matches and vector matches, fused into one
row per document.

The filters mean what the search eval's truth means (`apply_query` in `evals/search_set.py`):
people match the owner or a linked person; a document fits when its type is in `types` or its
area is in `areas`; a range applies to the field of the query's role, and a document with no
value there is left out of a filtered list; a place is a contained phrase of one of the type's
place fields.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date

from pydantic import JsonValue

from household_vault.db import DocumentRow, Store
from household_vault.doctypes import AREA, DocType
from household_vault.people import normalise_name
from household_vault.search.dates import DateRange
from household_vault.search.index import KeywordHit, KeywordIndex
from household_vault.search.query import Query
from household_vault.search.vectors import VectorHit, VectorIndex
from household_vault.search.vocab import (
    DATE_ROLES,
    KEY_FIELDS,
    PLACE_FIELDS,
    TYPE_LABELS,
)

POOL = 500  # hits taken from each ranking before fusing
UNFILTERED_VOTES = 5  # documents of the unfiltered rankings that vote in a filtered lookup


@dataclass(frozen=True)
class LineRef:
    page: int
    idx: int
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True)
class Row:
    document_id: str
    doc_type: DocType
    owner: str
    people: list[str]
    area: str
    rel_path: str
    doc_date: date
    key_fields: dict[str, JsonValue]
    date: date | None  # the role's date (the document date by default); None when it has none
    score: float
    lines: list[LineRef]
    vector: float = 0.0  # the best cosine of the document's chunks to a query vector
    word_hit: bool = False  # the query's residual words matched a line or a field by keyword


Rows = list[Row]


def rrf(rankings: Sequence[Sequence[str]], k: int = 60) -> list[tuple[str, float]]:
    """Reciprocal rank fusion: a document scores the sum of 1 / (k + rank) over the rankings that
    list it. Ties keep the order the documents were first seen."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda item: -item[1])


def _as_date(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _has_phrase(text: str, phrase: str) -> bool:
    words, want = normalise_name(text).split(), normalise_name(phrase).split()
    if not want:
        return False
    return any(words[i : i + len(want)] == want for i in range(len(words) - len(want) + 1))


def _role_date(doc: DocumentRow, role: str) -> date | None:
    if role == "document":
        return doc.doc_date if doc.date_source == "document" else None
    name = DATE_ROLES[doc.doc_type].get(role)  # type: ignore[call-overload]
    return _as_date(doc.fields.get(name)) if name else None


def _in_range(value: date, span: DateRange) -> bool:
    return (span.start is None or value >= span.start) and (span.end is None or value <= span.end)


def _filtered(query: Query) -> bool:
    return bool(
        query.people or query.types or query.areas or query.place or query.range is not None
    )


def _ids(hits: Sequence[KeywordHit] | Sequence[VectorHit]) -> list[str]:
    """The documents of a ranking, best first, each once."""
    return list(dict.fromkeys(h.document_id for h in hits))


class Searcher:
    def __init__(self, store: Store, keyword: KeywordIndex, vectors: VectorIndex) -> None:
        self.store = store
        self.keyword = keyword
        self.vectors = vectors

    # -- filters ---------------------------------------------------------------------------

    def _documents(self) -> Iterable[DocumentRow]:
        with self.store.lock:
            ids = [r[0] for r in self.store.conn.execute("select id from documents order by id")]
        for doc_id in ids:
            doc = self.store.document(doc_id)
            if doc is not None:
                yield doc

    def _matches(self, doc: DocumentRow, people: list[str], query: Query) -> bool:
        if query.people and not set(query.people) & set(people):
            return False
        if (query.types or query.areas) and not (
            doc.doc_type in query.types or AREA[doc.doc_type] in query.areas
        ):
            return False
        if query.place and not any(
            isinstance(v, str) and _has_phrase(v, query.place)
            for v in (doc.fields.get(f) for f in PLACE_FIELDS[doc.doc_type])
        ):
            return False
        if query.range is not None:
            when = _role_date(doc, query.role or "document")
            if when is None or not _in_range(when, query.range):
                return False
        return True

    def _candidates(self, query: Query) -> dict[str, DocumentRow]:
        found: dict[str, DocumentRow] = {}
        for doc in self._documents():
            people = [p for p, _ in self.store.people_of(doc.id)]
            if self._matches(doc, people, query):
                found[doc.id] = doc
        return found

    # -- rows ------------------------------------------------------------------------------

    def _row(
        self, doc: DocumentRow, score: float, hits: Sequence[KeywordHit], role: str | None
    ) -> Row:
        wanted = [(h.page, h.idx) for h in hits if h.kind == "line" and h.page is not None]
        lines: list[LineRef] = []
        if wanted:
            boxes = {(ln.page, ln.idx): ln.bbox for ln in self.store.lines_of(doc.id)}
            for page, idx in dict.fromkeys(wanted):
                if idx is not None and (page, idx) in boxes:
                    lines.append(LineRef(page, idx, boxes[(page, idx)]))
        key = {
            name: doc.fields[name]
            for name in KEY_FIELDS.get(doc.doc_type, ())
            if doc.fields.get(name) not in (None, "", [])
        }
        return Row(
            document_id=doc.id,
            doc_type=doc.doc_type,
            owner=doc.owner,
            people=[p for p, _ in self.store.people_of(doc.id)],
            area=doc.area,
            rel_path=doc.rel_path,
            doc_date=doc.doc_date,
            key_fields=key,
            date=_role_date(doc, role or "document"),
            score=score,
            lines=lines,
        )

    def _fuse(
        self,
        rankings: Sequence[Sequence[str]],
        keyword_hits: Sequence[Sequence[KeywordHit]],
        role: str | None,
        limit: int,
    ) -> Rows:
        """One row per document, fused over the rankings. The keyword hits give each row the
        lines that matched."""
        by_doc: dict[str, list[KeywordHit]] = {}
        for hits in keyword_hits:
            for h in hits:
                by_doc.setdefault(h.document_id, []).append(h)
        rows: Rows = []
        for doc_id, score in rrf(rankings)[:limit]:
            doc = self.store.document(doc_id)
            if doc is not None:
                rows.append(self._row(doc, score, by_doc.get(doc_id, []), role))
        return rows

    # -- the three entry points --------------------------------------------------------------

    def quick(self, text: str, limit: int = 20) -> Rows:
        """Keywords (the last word as a prefix) and vectors, fused. Runs no model."""
        kw = self.keyword.search(text, limit=POOL)
        vec = self.vectors.search(text, limit=POOL)
        return self._fuse([_ids(kw), _ids(vec)], [kw], None, limit)

    def lookup(self, query: Query, prompt: str, limit: int = 20) -> Rows:
        """The filters narrow the candidates; the query's words, place and type words (or the
        prompt when it has none) rank them."""
        allowed = self._candidates(query) if _filtered(query) else None
        only = None if allowed is None else set(allowed)  # rank inside the candidates
        base = " ".join(p for p in (query.words, query.place or "") if p).strip() or prompt
        text = " ".join([base, *(TYPE_LABELS[t] for t in query.types)])
        word_hits = (
            self.keyword.search(query.words, limit=POOL, prefix_last=False, only=only)
            if query.words.strip()
            else []
        )
        keyword_hits = [
            word_hits
            if p == query.words
            else self.keyword.search(p, limit=POOL, prefix_last=False, only=only)
            for p in (query.words, query.place or "")
            if p.strip()
        ] or [self.keyword.search(prompt, limit=POOL, prefix_last=False, only=only)]
        vec = self.vectors.search(text, limit=POOL, only=only)
        rankings = [_ids(hits) for hits in keyword_hits] + [_ids(vec)]
        # `vector` keeps the best of two cosines for a document: its chunks against the query's
        # words and type labels, and against the whole prompt. MIN_VECTOR is therefore a floor
        # on the better of the two, not on one fixed query text.
        best: dict[str, float] = {}
        votes = [vec]
        if allowed is not None:
            # The reading may have named the wrong person or type. The prompt's own keyword and
            # vector matches, unfiltered, vote too, so a misread filter cannot remove the
            # document they find. Only their first documents vote, so the filter still leads.
            quick_kw = self.keyword.search(prompt, limit=POOL)
            quick_vec = self.vectors.search(prompt, limit=POOL)
            keyword_hits = [*keyword_hits, quick_kw]
            rankings += [_ids(quick_kw)[:UNFILTERED_VOTES], _ids(quick_vec)[:UNFILTERED_VOTES]]
            votes.append(quick_vec)
        for hits in votes:
            for h in hits:
                best[h.document_id] = max(best.get(h.document_id, -1.0), h.score)
        found = {h.document_id for h in word_hits}
        rows = [
            replace(r, vector=best.get(r.document_id, 0.0), word_hit=r.document_id in found)
            for r in self._fuse(rankings, keyword_hits, query.role, limit)
        ]
        if allowed is not None and len(rows) < limit:
            # The filters named documents the rankings did not reach: they still answer.
            seen = {r.document_id for r in rows}
            rest = sorted(
                (d for d in allowed.values() if d.id not in seen),
                key=lambda d: (d.doc_date, d.id),
                reverse=True,
            )
            rows += [self._row(d, 0.0, [], query.role) for d in rest[: limit - len(rows)]]
        return rows

    def list(self, query: Query, limit: int = 500) -> Rows:
        """Every document the filters keep (and `words` match by keyword), by the role's date
        with the rows that have none last."""
        found = self._candidates(query)
        hits: dict[str, list[KeywordHit]] = {}
        if query.words.strip():
            for h in self.keyword.search(
                query.words, limit=100_000, prefix_last=False, only=set(found)
            ):
                hits.setdefault(h.document_id, []).append(h)
            found = {i: d for i, d in found.items() if i in hits}
        rows = [self._row(d, 0.0, hits.get(i, []), query.role) for i, d in found.items()]
        rows.sort(key=lambda r: (r.date is None, r.date or date.min, r.document_id))
        return rows[:limit]
