"""Search by meaning: each document becomes one summary chunk and windows of page lines, each
chunk becomes a vector, and a query is matched against all of them by cosine similarity.

The scan is exact and held in memory. A family vault of about a thousand documents is about
6,000 chunks, which fit in memory and scan in milliseconds, so an approximate index or a SQLite
extension would add nothing. Chunks hold only what the database already holds: the masked line
text and the stored fields.
"""

import threading
from dataclasses import dataclass
from typing import Protocol, cast

import numpy as np
from numpy.typing import NDArray

from household_vault.config import Settings
from household_vault.db import Store
from household_vault.reading.ollama import ModelError, ModelUnavailable, OllamaClient
from household_vault.schemas import SCHEMAS
from household_vault.schemas._coerce import field_kind
from household_vault.search.index import _value_text
from household_vault.search.vocab import FIELD_LABELS, TYPE_LABELS

WINDOW = 12
STEP = 9
BATCH = 16
# The line the Qwen3-Embedding model card puts before a query; documents are embedded plain.
QUERY_TASK = "Given a question about a household document, retrieve the passages that answer it"

Vectors = NDArray[np.float32]


@dataclass(frozen=True)
class Chunk:
    document_id: str
    page: int | None
    first: int | None
    last: int | None
    text: str


def chunks_of(store: Store, doc_id: str) -> list[Chunk]:
    """The summary chunk first (page, first and last are None), then per page windows of 12
    stored lines stepping 9, so each line is in at least one window."""
    doc = store.document(doc_id)
    if doc is None:
        return []
    names = {p.id: p.name for p in store.household().people}
    names["home"] = "Home"
    owner: list[str] = []
    linked: list[str] = []
    for person_id, role in store.people_of(doc_id):
        (owner if role == "owner" else linked).append(names.get(person_id, person_id))
    schema = SCHEMAS.get(doc.doc_type)
    summary = [TYPE_LABELS.get(doc.doc_type, doc.doc_type.value.replace("_", " "))]
    if owner:
        summary.append("Owner: " + ", ".join(owner))
    if linked:
        summary.append("Also for: " + ", ".join(linked))
    if doc.description:
        summary.append(doc.description)
    for name, value in doc.fields.items():
        if value is None or value == [] or value == "":
            continue
        kind = field_kind(schema, name) if schema and name in schema.model_fields else "text"
        label = FIELD_LABELS.get(name, name.replace("_", " "))
        summary.append(f"{label}: {_value_text(kind, value)}")
    chunks = [Chunk(doc_id, None, None, None, "\n".join(summary))]

    by_page: dict[int, list[tuple[int, str]]] = {}
    for ln in store.lines_of(doc_id):
        by_page.setdefault(ln.page, []).append((ln.idx, ln.text))
    for page, lines in sorted(by_page.items()):
        start = 0
        while True:
            window = lines[start : start + WINDOW]
            chunks.append(
                Chunk(doc_id, page, window[0][0], window[-1][0], "\n".join(t for _, t in window))
            )
            if start + WINDOW >= len(lines):
                break
            start += STEP
    return chunks


class Embedder(Protocol):
    name: str

    def embed_documents(self, texts: list[str]) -> Vectors: ...

    def embed_query(self, text: str) -> Vectors: ...


class OllamaEmbedder:
    def __init__(self, client: OllamaClient, model: str) -> None:
        self.client = client
        self.name = model

    def embed_documents(self, texts: list[str]) -> Vectors:
        rows: list[list[float]] = []
        for i in range(0, len(texts), BATCH):
            rows.extend(self.client.embed(self.name, texts[i : i + BATCH]))
        return np.asarray(rows, dtype=np.float32).reshape(len(texts), -1)

    def embed_query(self, text: str) -> Vectors:
        vec = self.client.embed(self.name, [f"Instruct: {QUERY_TASK}\nQuery:{text}"])[0]
        return np.asarray(vec, dtype=np.float32)


def embedder_for(settings: Settings) -> Embedder | None:
    """The real embedder, or None where no real models run (stand-in and recorded readers)."""
    if settings.reader != "mac":
        return None
    return OllamaEmbedder(OllamaClient(settings.ollama_url, timeout_s=120.0), settings.embed_model)


def _unit(rows: Vectors) -> Vectors:
    norms = np.linalg.norm(rows, axis=-1, keepdims=True)
    return cast(Vectors, (rows / np.where(norms == 0, 1.0, norms)).astype(np.float32))


@dataclass(frozen=True)
class VectorHit:
    document_id: str
    page: int | None
    first: int | None
    last: int | None
    score: float


class VectorIndex:
    def __init__(self, store: Store, embedder: Embedder | None) -> None:
        self.store = store
        self.embedder = embedder
        # Guards the in-memory matrix: a search never sees it half loaded.
        self._lock = threading.Lock()
        self._epoch = -1
        self._matrix: Vectors = np.zeros((0, 0), dtype=np.float32)
        self._rows: list[tuple[str, int | None, int | None, int | None]] = []

    def stale(self) -> bool:
        """The stored vectors came from another model than this embedder: they are not
        comparable, so search returns nothing until `vault index --rebuild`."""
        if self.embedder is None:
            return False
        with self.store.lock:
            row = self.store.conn.execute(
                "select value from meta where key = 'embed_model'"
            ).fetchone()
        return row is not None and row[0] != self.embedder.name

    def missing(self) -> list[tuple[str, int]]:
        """(document id, item id) of every filed document with no vectors."""
        with self.store.lock:
            rows = self.store.conn.execute(
                "select id, item_id from documents"
                " where id not in (select document_id from vectors) order by created_at, id"
            ).fetchall()
        return [(r[0], r[1]) for r in rows]

    def add(self, doc_id: str) -> int:
        """Embed a document and store its vectors, replacing any it had. Returns how many
        chunks. Needs Ollama (`ModelUnavailable` otherwise); does nothing with no embedder or
        when the stored vectors are from another model."""
        if self.embedder is None or self.stale():
            return 0
        chunks = chunks_of(self.store, doc_id)
        if not chunks:
            return 0
        vecs = _unit(self.embedder.embed_documents([c.text for c in chunks]))
        with self.store.lock, self.store.transaction():
            # The model call took a while: the document may have been undone meanwhile.
            if self.store.document(doc_id) is None:
                return 0
            self.store.conn.execute("delete from vectors where document_id = ?", (doc_id,))
            self.store.conn.executemany(
                "insert into vectors (document_id, page, first, last, model, dims, vec)"
                " values (?, ?, ?, ?, ?, ?, ?)",
                [
                    (doc_id, c.page, c.first, c.last, self.embedder.name, len(v), v.tobytes())
                    for c, v in zip(chunks, vecs, strict=True)
                ],
            )
            self.store.conn.execute(
                "insert or ignore into meta values ('embed_model', ?)", (self.embedder.name,)
            )
            self.store.vectors_epoch += 1
        return len(chunks)

    def remove(self, doc_id: str) -> None:
        with self.store.lock:
            self.store.conn.execute("delete from vectors where document_id = ?", (doc_id,))
            self.store.vectors_epoch += 1

    def rebuild(self) -> int:
        """Embed every document again with this embedder. Returns how many documents."""
        if self.embedder is None:
            return 0
        with self.store.lock:
            self.store.conn.execute("delete from vectors")
            self.store.conn.execute(
                "insert into meta values ('embed_model', ?)"
                " on conflict (key) do update set value = excluded.value",
                (self.embedder.name,),
            )
            self.store.vectors_epoch += 1
            ids = [r[0] for r in self.store.conn.execute("select id from documents order by id")]
        for doc_id in ids:
            self.add(doc_id)
        return len(ids)

    def _refresh(self) -> None:
        """Load the stored vectors again if they changed. Call with `self._lock` held."""
        if self._epoch == self.store.vectors_epoch:
            return
        assert self.embedder is not None
        with self.store.lock:
            epoch = self.store.vectors_epoch
            rows = self.store.conn.execute(
                "select document_id, page, first, last, dims, vec from vectors where model = ?"
                " order by id",
                (self.embedder.name,),
            ).fetchall()
        dims = rows[0]["dims"] if rows else 0
        rows = [r for r in rows if r["dims"] == dims]
        self._rows = [(r["document_id"], r["page"], r["first"], r["last"]) for r in rows]
        self._matrix = (
            np.stack([np.frombuffer(r["vec"], dtype=np.float32) for r in rows])
            if rows
            else np.zeros((0, 0), dtype=np.float32)
        )
        self._epoch = epoch

    def search(self, text: str, limit: int = 50) -> list[VectorHit]:
        """The chunks closest in meaning to the text. Empty with no embedder, a stale index,
        Ollama off or the model not pulled."""
        if self.embedder is None or not text.strip() or self.stale():
            return []
        try:
            query = _unit(self.embedder.embed_query(text))
        except (ModelUnavailable, ModelError):
            return []
        with self._lock:
            self._refresh()
            if len(self._rows) == 0 or self._matrix.shape[1] != query.shape[0]:
                return []
            scores = self._matrix @ query
            top = np.argsort(-scores)[:limit]
            hits = []
            for i in top:
                doc_id, page, first, last = self._rows[i]
                hits.append(VectorHit(doc_id, page, first, last, float(scores[i])))
            return hits
