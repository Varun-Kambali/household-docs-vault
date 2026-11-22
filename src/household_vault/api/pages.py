"""Page images, stored line text and Show in folder.

The filed copy is what is drawn. For a card that is the masked copy; the raw bytes of a card
photo are refused here as they are on the file routes, and so is every item that shares them.
"""

from collections.abc import Callable
from pathlib import PurePosixPath
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Path, Query, Request, Response
from fastapi.responses import JSONResponse

from household_vault.api.models import LineOut, PageLinesOut
from household_vault.app_state import AppState
from household_vault.filing.cardness import is_card_photo, shares_card_photo
from household_vault.intake.sniff import FileKind, sniff
from household_vault.pages import NoSuchPage, render_png
from household_vault.reading.ocr import EngineUnavailable
from household_vault.reading.render import DamagedFileError, LockedPdfError
from household_vault.reveal import RevealFailed
from household_vault.vaultroot import SECRETS_FILE, VaultPathError

NOT_HERE = "Show in folder works on the Mac itself, so the Drive path was copied instead."
NO_PAGE = "That page is not available."
CANNOT_DRAW = "That page cannot be drawn."
_MAC_HOSTS = ("localhost", "127.0.0.1", "[::1]")
_DRAWABLE = (FileKind.pdf, FileKind.jpeg, FileKind.png, FileKind.heic)

NOT_OPENED = "Show in folder did not work. Open the Drive path instead."
NO_FILE = "That file is not available."

PageNo = Annotated[int, Path(ge=0, le=10_000)]
Width = Annotated[int, Query(ge=320, le=2000)]


def is_mac_request(host: str) -> bool:
    """True only for the names that reach this app from the Mac itself."""
    return host.lower() in _MAC_HOSTS


def _hostname(header: str) -> str:
    """The host part of a Host header, without its port."""
    host = header.strip().lower()
    if host.startswith("["):
        return host[: host.find("]") + 1]
    return host.split(":", 1)[0]


def _private(rel: str) -> bool:
    parts = PurePosixPath(rel).parts
    low = rel.lower()
    return not parts or parts[0] == "_system" or rel == SECRETS_FILE or ".kdbx" in low


def add_page_routes(
    app: FastAPI,
    state: AppState,
    known_document: Callable[[str], Any],
    known_item: Callable[[int], Any],
    card_private: Callable[[], JSONResponse],
) -> None:

    def drawn(rel: str | None, page: int, width: int) -> Response:
        if rel is None or _private(rel):
            raise HTTPException(404, NO_PAGE)
        try:
            data = state.vault.read_bytes(rel)
        except VaultPathError:
            raise HTTPException(404, NO_PAGE) from None
        kind = sniff(data[:64])
        if kind not in _DRAWABLE:
            raise HTTPException(404, NO_PAGE)
        try:
            png = render_png(data, kind, page, width)
        except NoSuchPage:
            raise HTTPException(404, NO_PAGE) from None
        except (LockedPdfError, DamagedFileError, EngineUnavailable):
            raise HTTPException(409, CANNOT_DRAW) from None
        return Response(
            png,
            media_type="image/png",
            headers={
                "Cache-Control": "private, max-age=300",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "sandbox; default-src 'none'",
            },
        )

    def lines_of_document(doc_id: str, page: int) -> PageLinesOut:
        stored = state.store.lines_of(doc_id, page)
        return PageLinesOut(
            page=page, lines=[LineOut(idx=ln.idx, text=ln.text, bbox=ln.bbox) for ln in stored]
        )

    def lines_of_item(reading: dict[str, Any] | None, page: int) -> PageLinesOut:
        out: list[LineOut] = []
        for stored_page in (reading or {}).get("pages", []):
            if stored_page.get("page") == page:
                for idx, ln in enumerate(stored_page.get("lines", [])):
                    out.append(LineOut(idx=idx, text=ln["text"], bbox=tuple(ln["bbox"])))
        return PageLinesOut(page=page, lines=out)

    @app.get("/v1/documents/{doc_id}/pages/{page}.png", response_model=None)
    def document_page(doc_id: str, page: PageNo, width: Width = 1200) -> Response:
        doc = known_document(doc_id)
        if is_card_photo(state.store, doc.sha256):
            return card_private()
        return drawn(doc.rel_path, page, width)

    @app.get("/v1/documents/{doc_id}/pages/{page}/lines", response_model=None)
    def document_lines(doc_id: str, page: PageNo) -> PageLinesOut | JSONResponse:
        doc = known_document(doc_id)
        if is_card_photo(state.store, doc.sha256):
            return card_private()
        return lines_of_document(doc.id, page)

    @app.get("/v1/items/{item_id}/pages/{page}.png", response_model=None)
    def item_page(item_id: int, page: PageNo, width: Width = 1200) -> Response:
        item = known_item(item_id)
        if shares_card_photo(state.store, item):
            return card_private()
        return drawn(item.rel_path, page, width)

    @app.get("/v1/items/{item_id}/pages/{page}/lines", response_model=None)
    def item_lines(item_id: int, page: PageNo) -> PageLinesOut | JSONResponse:
        item = known_item(item_id)
        if shares_card_photo(state.store, item):
            return card_private()
        return lines_of_item(item.reading, page)

    @app.post("/v1/documents/{doc_id}/reveal", response_model=None)
    def reveal(doc_id: str, request: Request) -> Response:
        doc = known_document(doc_id)
        if is_card_photo(state.store, doc.sha256):
            return card_private()
        if not is_mac_request(_hostname(request.headers.get("host", ""))):
            return JSONResponse(status_code=409, content={"detail": NOT_HERE})
        if _private(doc.rel_path):
            raise HTTPException(404, NO_PAGE)
        try:
            if not state.vault.exists(doc.rel_path):
                raise HTTPException(404, NO_FILE)
            target = state.vault.path(doc.rel_path)
        except VaultPathError:
            raise HTTPException(404, NO_FILE) from None
        try:
            state.revealer.reveal(target)
        except RevealFailed:
            return JSONResponse(status_code=409, content={"detail": NOT_OPENED})
        return Response(status_code=204)
