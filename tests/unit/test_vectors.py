import time

import httpx
import numpy as np
import pytest

from household_vault.db import Store
from household_vault.reading.ollama import ModelError, ModelUnavailable, OllamaClient
from household_vault.search.vectors import (
    QUERY_TASK,
    Chunk,
    OllamaEmbedder,
    VectorIndex,
    chunks_of,
)
from tests.conftest import add_doc
from tests.fakes import FakeEmbedder


def vector_rows(store: Store, doc_id: str | None = None) -> int:
    sql, args = "select count(*) from vectors", ()
    if doc_id:
        sql, args = sql + " where document_id = ?", (doc_id,)
    return int(store.conn.execute(sql, args).fetchone()[0])


@pytest.fixture
def vectors(store: Store) -> VectorIndex:
    return VectorIndex(store, FakeEmbedder())


def many_lines(n: int) -> list[str]:
    return [f"line number {i}" for i in range(n)]


def test_chunks_cover_every_line_once_or_in_an_overlap_and_lead_with_the_summary(store):
    add_doc(store, "d1", "tax_invoice", {"seller": "Croma"}, many_lines(30))
    chunks = chunks_of(store, "d1")
    assert chunks[0].page is None and "Croma" in chunks[0].text
    assert "purchase invoice" in chunks[0].text and "seller: Croma" in chunks[0].text
    covered = {(c.page, i) for c in chunks[1:] for i in range(c.first, c.last + 1)}
    assert covered == {(ln.page, ln.idx) for ln in store.lines_of("d1")}
    assert [(c.first, c.last) for c in chunks[1:]] == [(0, 11), (9, 20), (18, 29)]


def test_a_short_page_is_one_window_and_an_empty_one_has_none(store):
    add_doc(store, "d1", "tax_invoice", {"seller": "Croma"}, many_lines(12))
    add_doc(store, "d2", "tax_invoice", {"seller": "Voltas"}, [])
    assert [(c.first, c.last) for c in chunks_of(store, "d1")[1:]] == [(0, 11)]
    assert len(chunks_of(store, "d2")) == 1
    assert chunks_of(store, "nobody") == []


def test_vector_search_finds_by_meaning(store, vectors):
    add_doc(store, "fridge-invoice", "tax_invoice", {"seller": "Croma"}, ["Samsung fridge 253 L"])
    add_doc(store, "other", "tax_invoice", {"seller": "Reliance"}, ["Cotton shirt blue"])
    vectors.add("fridge-invoice")
    vectors.add("other")
    hits = vectors.search("refrigerator bill")
    assert hits[0].document_id == "fridge-invoice"
    assert hits[0].score > hits[-1].score
    assert vectors.search("   ") == []


def test_adding_again_replaces_the_documents_vectors(store, vectors):
    add_doc(store, "d1", "tax_invoice", {"seller": "Croma"}, many_lines(30))
    first = vectors.add("d1")
    assert vectors.add("d1") == first == vector_rows(store, "d1")


def test_removed_vectors_never_return(vectors_vault):  # Review Focus 12
    doc = vectors_vault.file("tax_invoice-1-clean")
    vectors = vectors_vault.world.vectors
    assert vector_rows(vectors_vault.store, doc.id) > 0
    assert any(h.document_id == doc.id for h in vectors.search("Croma"))  # loads the matrix
    vectors_vault.undo(doc.id)
    assert vector_rows(vectors_vault.store) == 0
    assert all(h.document_id != doc.id for h in vectors.search("Croma"))


def test_embed_jobs_follow_filing(vectors_vault):
    vectors_vault.file("tax_invoice-1-clean")
    assert vector_rows(vectors_vault.store) > 0


def test_a_filing_while_ollama_is_off_keeps_the_document_and_the_job_waits(vectors_vault):
    embedder = vectors_vault.world.vectors.embedder
    embedder.fail = ModelUnavailable("Ollama is not running")
    doc = vectors_vault.file("tax_invoice-1-clean")
    store = vectors_vault.store
    assert store.document(doc.id) is not None and vector_rows(store) == 0
    job = store.conn.execute("select state, attempts from jobs where kind = 'embed'").fetchone()
    assert (job["state"], job["attempts"]) == ("queued", 1)
    assert store.item(doc.item_id).state == "filed"


def test_a_failing_embed_does_not_hold_the_document(vectors_vault):
    vectors_vault.world.vectors.embedder.fail = ModelError("broken")
    doc = vectors_vault.file("tax_invoice-1-clean")
    assert vectors_vault.store.item(doc.item_id).state == "filed"
    assert (
        vectors_vault.store.conn.execute("select state from jobs where kind = 'embed'").fetchone()[
            0
        ]
        == "done"
    )


def test_start_up_queues_every_filed_document_that_has_no_vectors(vectors_vault):
    doc = vectors_vault.file("tax_invoice-1-clean")
    store, w = vectors_vault.store, vectors_vault.world
    store.conn.execute("delete from vectors")  # as in a database migrated from version 1
    store.conn.execute("delete from meta where key = 'embed_model'")
    w.worker.start_up()
    w.worker.start_up()  # twice: still one waiting job
    assert (
        store.conn.execute(
            "select count(*) from jobs where kind = 'embed' and state = 'queued'"
        ).fetchone()[0]
        == 1
    )
    w.drain()
    assert vector_rows(store, doc.id) > 0


def test_a_different_embed_model_marks_the_index_stale_until_rebuilt(store, vectors):
    add_doc(store, "d1", "tax_invoice", {"seller": "Croma"}, ["Croma Electronics"])
    vectors.add("d1")
    other = VectorIndex(store, FakeEmbedder(name="other"))
    assert other.stale() and other.search("Croma") == []
    assert other.add("d1") == 0  # new vectors would be mixed with the old ones
    assert not vectors.stale()
    assert other.rebuild() == 1
    assert not other.stale() and other.search("Croma")[0].document_id == "d1"


def test_rebuild_embeds_every_document_again(store, vectors):
    add_doc(store, "a", "tax_invoice", {"seller": "Croma"}, ["Croma"])
    add_doc(store, "b", "tax_invoice", {"seller": "Voltas"}, ["Voltas"])
    assert vectors.rebuild() == 2
    assert vector_rows(store, "a") > 0 and vector_rows(store, "b") > 0
    assert vectors.missing() == []


def test_no_embedder_means_no_hits(store):
    add_doc(store, "d1", "tax_invoice", {"seller": "Croma"}, ["Croma"])
    none = VectorIndex(store, None)
    assert none.add("d1") == 0 and none.search("Croma") == [] and not none.stale()


def test_ollama_off_means_no_vector_hits_not_an_error(store):  # Review Focus 13
    add_doc(store, "d1", "tax_invoice", {"seller": "Croma"}, ["Croma"])
    VectorIndex(store, FakeEmbedder()).add("d1")
    dead = OllamaEmbedder(OllamaClient("http://127.0.0.1:9", timeout_s=0.5), "fake-embed")
    assert VectorIndex(store, dead).search("fridge") == []


def test_a_search_after_another_thread_changes_the_vectors_sees_the_new_ones(store, vectors):
    add_doc(store, "a", "tax_invoice", {"seller": "Croma"}, ["fridge"])
    add_doc(store, "b", "tax_invoice", {"seller": "Voltas"}, ["fridge"])
    vectors.add("a")
    assert {h.document_id for h in vectors.search("fridge")} == {"a"}
    vectors.add("b")
    assert {h.document_id for h in vectors.search("fridge")} == {"a", "b"}
    store.remove_document("a")
    assert {h.document_id for h in vectors.search("fridge")} == {"b"}


def test_an_exact_scan_of_ten_thousand_vectors_is_fast():
    rng = np.random.default_rng(0)
    matrix = rng.standard_normal((10_000, 1024)).astype(np.float32)
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
    query = matrix[7]
    start = time.perf_counter()
    top = np.argsort(-(matrix @ query))[:50]
    assert time.perf_counter() - start < 0.05
    assert top[0] == 7


def ollama(handler):
    return OllamaClient("http://ollama.test", transport=httpx.MockTransport(handler))


def test_embed_posts_the_texts_and_reads_the_vectors():
    seen = {}

    def handler(request):
        seen["path"], seen["body"] = request.url.path, request.read()
        return httpx.Response(200, json={"embeddings": [[1.0, 0.0], [0.0, 2.0]]})

    out = ollama(handler).embed("m", ["a", "b"])
    assert out == [[1.0, 0.0], [0.0, 2.0]] and seen["path"] == "/api/embed"
    assert b'"input":["a","b"]' in seen["body"].replace(b" ", b"")
    assert b'"keep_alive":"30m"' in seen["body"].replace(b" ", b"")


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx.Response(404), ModelUnavailable),
        (httpx.Response(500, text="secret prompt echoed"), ModelError),
        (httpx.Response(200, json={"nope": 1}), ModelError),
        (httpx.Response(200, json={"embeddings": [[1.0]]}), ModelError),  # two texts, one vector
    ],
)
def test_embed_maps_errors_like_chat(response, error):
    with pytest.raises(error) as exc:
        ollama(lambda request: response).embed("m", ["a", "b"])
    assert "secret" not in str(exc.value)


def test_embed_when_ollama_is_not_running():
    with pytest.raises(ModelUnavailable):
        OllamaClient("http://127.0.0.1:9", timeout_s=0.5).embed("m", ["a"])


def test_queries_carry_the_instruction_and_documents_do_not():
    texts = []

    def handler(request):
        import json

        sent = json.loads(request.read())["input"]
        texts.extend(sent)
        return httpx.Response(200, json={"embeddings": [[3.0, 4.0]] * len(sent)})

    emb = OllamaEmbedder(ollama(handler), "m")
    emb.embed_documents(["plain page"])
    emb.embed_query("fridge bill")
    assert texts == ["plain page", f"Instruct: {QUERY_TASK}\nQuery:fridge bill"]


def test_chat_json_options_override_the_defaults_and_keep_the_rest():
    import json

    bodies = []

    def handler(request):
        bodies.append(json.loads(request.read()))
        return httpx.Response(200, json={"message": {"content": "{}"}})

    client = ollama(handler)
    client.chat_json("m", "s", "u", [], {}, False)
    client.chat_json("m", "s", "u", [], {}, False, options={"num_ctx": 4096, "num_predict": 400})
    assert bodies[0]["options"] == {"temperature": 0, "num_ctx": 12288, "num_predict": 1500}
    assert bodies[1]["options"] == {"temperature": 0, "num_ctx": 4096, "num_predict": 400}


def test_chunk_is_a_plain_record():
    assert Chunk("d", None, None, None, "t").text == "t"
