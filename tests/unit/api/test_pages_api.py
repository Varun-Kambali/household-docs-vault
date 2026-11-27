import io

import pytest
from PIL import Image

from household_vault import pages
from household_vault.api.pages import is_mac_request
from household_vault.intake.sniff import FileKind
from household_vault.reading.render import page_count
from household_vault.reasons import Reason


def png_size(data: bytes) -> tuple[int, int]:
    assert data.startswith(b"\x89PNG")
    with Image.open(io.BytesIO(data)) as img:
        return img.size


def jpeg(size, orientation=None, colour=(200, 30, 30)) -> bytes:
    img = Image.new("RGB", size, colour)
    exif = Image.Exif()
    if orientation:
        exif[0x0112] = orientation
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


def overwrite(state, doc, data: bytes) -> None:
    state.vault.path(doc.rel_path).write_bytes(data)


@pytest.fixture
def photo_doc(search_state):
    docs = [
        d
        for d in map(search_state.store.document, _ids(search_state))
        if d.rel_path.lower().endswith(".jpg")
    ]
    return docs[0]


def _ids(state) -> list[str]:
    with state.store.lock:
        return [r[0] for r in state.store.conn.execute("select id from documents order by id")]


def test_a_page_comes_back_as_a_png_of_the_asked_width(search_client, photo_doc):
    r = search_client.get(f"/v1/documents/{photo_doc.id}/pages/0.png", params={"width": 800})
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert png_size(r.content)[0] == 800
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-content-type-options"] == "nosniff"
    default = search_client.get(f"/v1/documents/{photo_doc.id}/pages/0.png")
    assert png_size(default.content)[0] == 1200


@pytest.mark.parametrize("width", [319, 2001, 0, -5])
def test_the_width_is_kept_between_320_and_2000(search_client, photo_doc, width):
    r = search_client.get(f"/v1/documents/{photo_doc.id}/pages/0.png", params={"width": width})
    assert r.status_code == 422


def test_a_pdf_page_is_drawn_and_a_missing_page_is_a_404(search_client, search_state):
    from household_vault.doctypes import DocType
    from tests.conftest import drop, fileable

    drop(search_state.vault, "policy.pdf", fileable(DocType.warranty_card).data)
    search_state.worker.drain()
    (doc,) = [
        d
        for d in search_state.store.documents_of_type(DocType.warranty_card)
        if d.rel_path.endswith(".pdf")
    ]
    r = search_client.get(f"/v1/documents/{doc.id}/pages/0.png", params={"width": 500})
    assert r.status_code == 200 and png_size(r.content)[0] == 500
    count = page_count(search_state.vault.read_bytes(doc.rel_path))
    assert search_client.get(f"/v1/documents/{doc.id}/pages/{count}.png").status_code == 404
    assert search_client.get(f"/v1/documents/{doc.id}/pages/1.png").status_code == (
        200 if count > 1 else 404
    )


def test_a_photo_has_one_page(search_client, photo_doc):
    assert search_client.get(f"/v1/documents/{photo_doc.id}/pages/1.png").status_code == 404
    assert search_client.get("/v1/documents/nope/pages/0.png").status_code == 404


def test_a_rotated_photo_page_matches_the_reading_frame(search_client, search_state, photo_doc):
    # The stored boxes were measured on the image `open_image` returns (upright, the rotation
    # tag applied), so the page is that image: 400 x 200 stored with tag 6 is 200 x 400.
    overwrite(search_state, photo_doc, jpeg((400, 200), orientation=6))
    r = search_client.get(f"/v1/documents/{photo_doc.id}/pages/0.png", params={"width": 400})
    width, height = png_size(r.content)
    assert abs(width / height - 200 / 400) < 0.01


def test_card_pages_come_from_the_masked_copy_and_raw_card_bytes_are_refused(
    search_client, search_state, photo_doc
):
    masked = jpeg((300, 150), colour=(0, 200, 0))
    overwrite(search_state, photo_doc, masked)  # the filed copy is the masked one
    r = search_client.get(f"/v1/documents/{photo_doc.id}/pages/0.png", params={"width": 320})
    assert r.status_code == 200
    with Image.open(io.BytesIO(r.content)) as img:
        assert img.getpixel((10, 10))[1] > 150  # the filed copy's pixels
    # These bytes were once a card photo: refused on both routes.
    item = search_state.store.add_item(
        photo_doc.sha256, "card.jpg", None, search_state.worker.clock()
    )
    search_state.store.update_item(item.id, state="gone", reading={"doc_type": "card_front"})
    for tail in ("pages/0.png", "pages/0/lines"):
        r = search_client.get(f"/v1/documents/{photo_doc.id}/{tail}")
        assert r.status_code == 423 and "secrets store" in r.json()["detail"]


def test_the_lines_route_gives_the_stored_text_and_boxes(search_client, search_state, photo_doc):
    out = search_client.get(f"/v1/documents/{photo_doc.id}/pages/0/lines").json()
    stored = search_state.store.lines_of(photo_doc.id, 0)
    assert out["page"] == 0 and len(out["lines"]) == len(stored) > 0
    first = out["lines"][0]
    assert first["text"] == stored[0].text and first["idx"] == stored[0].idx
    assert first["bbox"] == list(stored[0].bbox)
    assert search_client.get(f"/v1/documents/{photo_doc.id}/pages/7/lines").json()["lines"] == []


@pytest.fixture
def waiting_item(search_state):
    from household_vault.doctypes import DocType
    from tests.conftest import drop, fileable

    search_state.engines.models.patch = {"patient": "Anita Sharma"}
    drop(search_state.vault, "rx.pdf", fileable(DocType.prescription).data)
    search_state.worker.drain()
    (item,) = search_state.store.items(["asked"])
    return item


def test_a_needs_a_look_file_has_pages_and_lines(search_client, waiting_item):
    r = search_client.get(f"/v1/items/{waiting_item.id}/pages/0.png", params={"width": 600})
    assert r.status_code == 200 and png_size(r.content)[0] == 600
    out = search_client.get(f"/v1/items/{waiting_item.id}/pages/0/lines").json()
    assert out["page"] == 0 and out["lines"]
    assert search_client.get("/v1/items/999/pages/0.png").status_code == 404


def test_a_waiting_card_items_pages_are_refused(search_client, search_state, waiting_item):
    search_state.store.update_item(waiting_item.id, reasons=[Reason.card_unreadable])
    for tail in ("pages/0.png", "pages/0/lines"):
        r = search_client.get(f"/v1/items/{waiting_item.id}/{tail}")
        assert r.status_code == 423 and "secrets store" in r.json()["detail"]


def test_rendered_pages_are_kept_in_a_lru_of_64(monkeypatch):
    calls = []
    real = pages._draw

    def counting(data, kind, page, width):
        calls.append((len(data), page, width))
        return real(data, kind, page, width)

    monkeypatch.setattr(pages, "_draw", counting)
    pages.clear_cache()
    data = jpeg((50, 50))
    first = pages.render_png(data, FileKind.jpeg, 0, 320)
    assert pages.render_png(data, FileKind.jpeg, 0, 320) == first and len(calls) == 1
    for width in range(321, 321 + 64):
        pages.render_png(data, FileKind.jpeg, 0, width)
    pages.render_png(data, FileKind.jpeg, 0, 320)  # pushed out by 64 newer pages
    assert len(calls) == 66


def test_render_png_scales_to_the_width_and_keeps_the_ratio():
    pages.clear_cache()
    out = pages.render_png(jpeg((400, 100)), FileKind.jpeg, 0, 800)
    assert png_size(out) == (800, 200)


def test_reveal_runs_on_the_mac_only(search_client, search_state, fake_revealer, filed_ids):
    doc_id = filed_ids[0]
    doc = search_state.store.document(doc_id)
    r = search_client.post(f"/v1/documents/{doc_id}/reveal", headers={"host": "127.0.0.1"})
    assert r.status_code == 204
    assert fake_revealer.paths == [search_state.vault.path(doc.rel_path)]
    # Task 21's host allow-list refuses other names today (400); the route's own check answers 409
    # once the tailnet name is allowed. Either way `open` never runs.
    r = search_client.post(
        f"/v1/documents/{doc_id}/reveal", headers={"host": "vault.example.ts.net"}
    )
    assert r.status_code in (400, 409) and len(fake_revealer.paths) == 1
    assert is_mac_request("127.0.0.1") and is_mac_request("localhost") and is_mac_request("[::1]")
    assert not is_mac_request("vault.example.ts.net") and not is_mac_request("")


def test_reveal_answers_409_from_its_own_check(settings, tmp_path, clock, fake_revealer):
    from fastapi.testclient import TestClient

    from household_vault.api.app import create_app
    from tests.unit.api.conftest import _build, _file

    wide = settings.model_copy(update={"host": "0.0.0.0"})  # no host allow-list: the route decides
    s = _build(wide, tmp_path, clock, revealer=fake_revealer)
    try:
        _file(s, "tax_invoice-1-photo")
        (doc_id,) = _ids(s)
        c = TestClient(create_app(s, start_worker=False), base_url="http://vault.example.ts.net")
        r = c.post(f"/v1/documents/{doc_id}/reveal")
        assert r.status_code == 409 and r.json()["detail"] == (
            "Show in folder works on the Mac itself, so the Drive path was copied instead."
        )
        assert fake_revealer.paths == []
    finally:
        s.gate.lock()
        s.store.conn.close()


def test_reveal_refuses_a_card_photo_and_an_unknown_document(
    search_client, search_state, filed_ids, fake_revealer
):
    doc = search_state.store.document(filed_ids[0])
    item = search_state.store.add_item(doc.sha256, "card.jpg", None, search_state.worker.clock())
    search_state.store.update_item(item.id, state="gone", reading={"doc_type": "card_front"})
    assert search_client.post(f"/v1/documents/{doc.id}/reveal").status_code == 423
    assert search_client.post("/v1/documents/nope/reveal").status_code == 404
    assert fake_revealer.paths == []


def test_the_mac_revealer_runs_open_without_a_shell(monkeypatch, tmp_path):
    import subprocess

    from household_vault.reveal import MacRevealer

    seen = {}

    def fake_run(args, **kwargs):
        seen["args"], seen["kwargs"] = args, kwargs
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr("household_vault.reveal.subprocess.run", fake_run)
    MacRevealer().reveal(tmp_path / "a b.pdf")
    assert seen["args"] == ["open", "-R", str(tmp_path / "a b.pdf")]
    assert not seen["kwargs"].get("shell")


@pytest.mark.parametrize("page", ["99999999999999999999", "-1", "10001"])
@pytest.mark.parametrize("tail", ["pages/{page}.png", "pages/{page}/lines"])
def test_a_page_number_out_of_range_is_a_422_on_every_page_route(
    search_client, photo_doc, waiting_item, page, tail
):
    for base in (f"/v1/documents/{photo_doc.id}", f"/v1/items/{waiting_item.id}"):
        r = search_client.get(f"{base}/{tail.format(page=page)}")
        assert r.status_code == 422, (base, tail, page)


def test_reveal_of_a_file_gone_from_drive_is_a_404(
    search_client, search_state, filed_ids, fake_revealer
):
    doc = search_state.store.document(filed_ids[0])
    search_state.vault.unlink(doc.rel_path)
    r = search_client.post(f"/v1/documents/{doc.id}/reveal")
    assert r.status_code == 404 and r.json()["detail"] == "That file is not available."
    assert fake_revealer.paths == []


def test_a_revealer_that_fails_is_a_409_without_the_path(
    search_client, search_state, filed_ids, fake_revealer
):
    from household_vault.reveal import RevealFailed

    def fail(path):
        raise RevealFailed(str(path))

    fake_revealer.reveal = fail
    r = search_client.post(f"/v1/documents/{filed_ids[0]}/reveal")
    doc = search_state.store.document(filed_ids[0])
    assert r.status_code == 409 and doc.rel_path not in r.text
    assert str(search_state.vault.root) not in r.text


def test_the_mac_revealer_times_out_and_reports_a_bad_exit(monkeypatch, tmp_path):
    import subprocess

    from household_vault.reveal import MacRevealer, RevealFailed

    seen = {}

    def slow(args, **kwargs):
        seen.update(kwargs)
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])

    monkeypatch.setattr("household_vault.reveal.subprocess.run", slow)
    with pytest.raises(RevealFailed):
        MacRevealer().reveal(tmp_path / "a.pdf")
    assert seen["timeout"] == 5

    monkeypatch.setattr(
        "household_vault.reveal.subprocess.run",
        lambda args, **kw: subprocess.CompletedProcess(args, 1),
    )
    with pytest.raises(RevealFailed):
        MacRevealer().reveal(tmp_path / "a.pdf")


def test_both_lines_routes_declare_their_reply_in_the_schema(search_client):
    schema = search_client.app.openapi()
    for path in (
        "/v1/documents/{doc_id}/pages/{page}/lines",
        "/v1/items/{item_id}/pages/{page}/lines",
    ):
        ok = schema["paths"][path]["get"]["responses"]["200"]
        assert ok["content"]["application/json"]["schema"]["$ref"].endswith("/PageLinesOut")


def test_page_images_and_lines_are_never_kept_by_the_browser(
    search_client, photo_doc, waiting_item
):
    """An ID page must not land in the browser's disk cache."""
    for path in (
        f"/v1/documents/{photo_doc.id}/pages/0.png",
        f"/v1/documents/{photo_doc.id}/pages/0/lines",
        f"/v1/items/{waiting_item.id}/pages/0.png",
        f"/v1/items/{waiting_item.id}/pages/0/lines",
    ):
        r = search_client.get(path)
        assert r.status_code == 200 and r.headers["cache-control"] == "no-store", path
