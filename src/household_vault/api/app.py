"""The routes. Each handler asks `Actions` (or reads the store) and maps the answer to a status:
404 for an unknown id or a path `VaultRoot` refuses, 409 with the message for a refused answer or
Undo, 423 for a locked secrets store, 413 for a large upload.

Request bodies are never logged and the error responses carry fixed messages, so a password or a
card number sent in a body cannot come back in a response or reach the log. Master passwords and
PDF passwords travel only in request bodies.
"""

from __future__ import annotations

import dataclasses
import logging
import threading
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import PurePosixPath
from typing import Annotated, Any

from fastapi import FastAPI, Form, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.formparsers import MultiPartParser
from starlette.middleware.trustedhost import TrustedHostMiddleware

from household_vault import __version__
from household_vault.actions import AnswerError, PartlyAnswered
from household_vault.activity import ActivityEntry
from household_vault.api.models import (
    ActivityOut,
    AnswerIn,
    AnswerManyIn,
    CardOut,
    DocumentOut,
    Health,
    ItemOut,
    MasterPasswordIn,
    NeedsALookOut,
    OptionOut,
    ProgressOut,
    QuestionOut,
    UnlockIn,
)
from household_vault.app_state import AppState
from household_vault.db import Item
from household_vault.emergency import sheet_html
from household_vault.filing.filer import TargetGone, UndoError
from household_vault.filing.questions import Option, Question, question_for
from household_vault.filing.records import DocumentRecord
from household_vault.logging_setup import configure
from household_vault.reading.ollama import ModelUnavailable
from household_vault.reasons import Reason
from household_vault.secrets.cards import CardUploadError
from household_vault.secrets.mask import MaskError
from household_vault.secrets.store import SecretsLocked
from household_vault.vaultroot import SECRETS_FILE, VaultGone, VaultPathError

log = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # a file
_MAX_BODY_BYTES = 2 * MAX_UPLOAD_BYTES + 1024 * 1024  # two files and the form around them
_LOCAL_HOSTS = ("localhost", "127.0.0.1", "[::1]", "::1", "testserver")
_MEDIA = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".heic": "image/heic",
}
_COPY_REASONS = (Reason.duplicate, Reason.possible_copy)

GONE_FILE = "The file is no longer there. Nothing was changed."
GONE_FOLDER = "The folder is not there at the moment. Nothing was changed. Try again in a moment."
NOT_ALLOWED = "That path is not available. Nothing was changed."
VAULT_AWAY = "The vault folder cannot be reached right now. Nothing was changed."
READER_DOWN = "The reader is not running. Start Ollama and try again."
BAD_PHOTO = "That photo could not be used. Upload a clearer, straighter photo of the card."
TOO_LARGE = "That photo is too large. Photos can be up to 25 MB."
OTHER_COPY_GONE = "The other copy is no longer there. Nothing will be deleted."
ONLY_COPY = (
    "This deletes the only copy of the file (Drive keeps it in its trash for 30 days). "
    "Confirm to go on."
)
SECRETS_EXIST = "The secrets file already exists. Unlock it instead of making a new one."
SECRETS_SYNCING = (
    "A secrets file may still be syncing from Drive. Wait until Drive has finished, then try again."
)
SECRETS_MISSING = (
    "Cards are filed here and their numbers are kept in Secrets.kdbx, which is not in the "
    "folder. Restore Secrets.kdbx (from Drive's trash or a backup) instead of making a new one, "
    "because a new file would lose those numbers."
)
SOMETHING_WENT_WRONG = "Something went wrong. Nothing was changed."
NOT_UNDERSTOOD = "The request was not understood."


def _detail(status: int, message: str, **extra: Any) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": message, **extra})


def _is_syncing(name: str) -> bool:
    """A name beside the secrets file that Drive or another app leaves while a copy of the file
    is on its way: a conflict copy ("Secrets (1).kdbx"), or a temporary or partial download."""
    return name != SECRETS_FILE and name.lower().lstrip(".").startswith("secrets")


def create_app(state: AppState, *, start_worker: bool = True) -> FastAPI:
    settings = state.settings
    configure(settings.log_dir)
    # Uploads stay in memory (the default spools files over 1 MB to a temporary file on disk, and
    # a card photo is never written anywhere but the secrets store).
    MultiPartParser.spool_max_size = MAX_UPLOAD_BYTES + 1024 * 1024

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        stop = threading.Event()
        thread: threading.Thread | None = None
        if start_worker:
            thread = threading.Thread(
                target=state.worker.run_forever, args=(stop,), name="worker", daemon=True
            )
            thread.start()
        try:
            yield
        finally:
            stop.set()
            if thread is not None:
                thread.join(timeout=15)
            state.gate.lock()

    app = FastAPI(
        title="household-docs-vault",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    if settings.host in ("localhost", "127.0.0.1", "::1"):
        # A page on another site cannot reach this app through a name that points here.
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(_LOCAL_HOSTS))

    @app.middleware("http")
    async def limit_body(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        length = request.headers.get("content-length", "")
        if length.isdigit() and int(length) > _MAX_BODY_BYTES:
            return _detail(413, TOO_LARGE)
        return await call_next(request)

    # -- errors --------------------------------------------------------------------------------

    @app.exception_handler(PartlyAnswered)
    async def _partly(_: Request, exc: PartlyAnswered) -> JSONResponse:
        return _detail(
            409,
            str(exc),
            answered=[i.id for i in exc.answered],
            refused={str(k): v for k, v in exc.refused.items()},
        )

    @app.exception_handler(AnswerError)
    async def _answer_error(_: Request, exc: AnswerError) -> JSONResponse:
        return _detail(409, str(exc))

    @app.exception_handler(UndoError)
    async def _undo_error(_: Request, exc: UndoError) -> JSONResponse:
        return _detail(409, str(exc))

    @app.exception_handler(SecretsLocked)
    async def _locked(_: Request, exc: SecretsLocked) -> JSONResponse:
        return _detail(423, str(exc))

    @app.exception_handler(VaultGone)
    async def _gone(_: Request, exc: VaultGone) -> JSONResponse:
        return _detail(409, GONE_FILE)

    @app.exception_handler(TargetGone)
    async def _target_gone(_: Request, exc: TargetGone) -> JSONResponse:
        return _detail(409, GONE_FOLDER)

    @app.exception_handler(VaultPathError)
    async def _path(_: Request, exc: VaultPathError) -> JSONResponse:
        return _detail(409, NOT_ALLOWED)

    @app.exception_handler(CardUploadError)
    async def _upload_error(_: Request, exc: CardUploadError) -> JSONResponse:
        return _detail(422, str(exc))

    @app.exception_handler(MaskError)
    async def _mask_error(_: Request, exc: MaskError) -> JSONResponse:
        return _detail(422, BAD_PHOTO)

    @app.exception_handler(ModelUnavailable)
    async def _reader_down(_: Request, exc: ModelUnavailable) -> JSONResponse:
        return _detail(503, READER_DOWN)

    @app.exception_handler(OSError)
    async def _os_error(_: Request, exc: OSError) -> JSONResponse:
        log.warning("a request failed: %s", type(exc).__name__)
        return _detail(503, VAULT_AWAY)

    @app.exception_handler(RequestValidationError)
    async def _invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
        # The default response repeats the input, which can be a password.
        where = [".".join(str(p) for p in e["loc"]) for e in exc.errors()]
        return _detail(422, NOT_UNDERSTOOD, fields=where)

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        log.warning("a request failed: %s", type(exc).__name__)
        return _detail(500, SOMETHING_WENT_WRONG)

    # -- helpers -------------------------------------------------------------------------------

    def known_item(item_id: int) -> Item:
        try:
            return state.store.item(item_id)
        except KeyError:
            raise HTTPException(404, "That file is not in the list.") from None

    def known_document(doc_id: str) -> Any:
        doc = state.store.document(doc_id)
        if doc is None:
            raise HTTPException(404, "That document is not in the vault.")
        return doc

    def serve(rel: str | None) -> Response:
        if rel is None:
            raise HTTPException(404, "That file is not available.")
        try:
            data = state.vault.read_bytes(rel)
        except VaultPathError:  # outside the vault, a link, gone: all the same to the caller
            raise HTTPException(404, "That file is not available.") from None
        media = _MEDIA.get(PurePosixPath(rel).suffix.lower(), "application/octet-stream")
        return Response(
            data,
            media_type=media,
            headers={"X-Content-Type-Options": "nosniff", "Content-Disposition": "inline"},
        )

    def live_question(item: Item) -> Question | None:
        """The item's question. A copy question is rebuilt from a live check, so it names where
        the other copy is now, or says it is gone and offers only to keep both."""
        stored = item.question
        if stored is None:
            return None
        question = Question(
            Reason(stored["reason"]),
            stored["text"],
            stored["answer_kind"],
            [Option(o["value"], o["label"]) for o in stored["options"]],
            stored.get("field"),
        )
        if question.reason not in _COPY_REASONS:
            return question
        path = state.actions.other_copy_path(item)
        if path is None:
            keep = [o for o in question.options if o.value == "keep_both"]
            return dataclasses.replace(question, text=OTHER_COPY_GONE, options=keep)
        context = {"path": path}
        other_id = item.overrides.get("copy_of")
        other = state.store.document(other_id) if isinstance(other_id, str) else None
        if other is not None:
            context["date"] = other.created_at.date().isoformat()
        return question_for([question.reason], None, state.household, context)

    def question_out(question: Question) -> QuestionOut:
        return QuestionOut(
            reason=question.reason.value,
            text=question.text,
            answer_kind=question.answer_kind,
            options=[OptionOut(value=o.value, label=o.label) for o in question.options],
            field=question.field,
        )

    def actions_of(item: Item) -> list[str]:
        if item.state == "filed" and item.document_id is not None:
            return ["open", "undo"]
        if item.state == "held":
            return ["retry"]
        if item.state != "asked":
            return []
        question = live_question(item)
        out = ["open", "undo"]
        if question is None:
            return out
        if question.answer_kind == "copy":
            out += [o.value for o in question.options]
        elif question.answer_kind == "unlock":
            out.append("unlock")
        else:
            out.append("answer")
        return out

    def newest_entry_ids(entries: list[ActivityEntry]) -> dict[int, int]:
        ids = sorted({e.item_id for e in entries if e.item_id is not None})
        if not ids:
            return {}
        marks = ",".join("?" * len(ids))
        with state.store.lock:
            rows = state.store.conn.execute(
                f"select item_id, max(id) from activity where item_id in ({marks}) "
                "group by item_id",
                ids,
            ).fetchall()
        return {r[0]: r[1] for r in rows}

    def activity_out(entry: ActivityEntry, newest: dict[int, int]) -> ActivityOut:
        actions: list[str] = []
        if entry.item_id is not None and newest.get(entry.item_id) == entry.id:
            try:
                actions = actions_of(state.store.item(entry.item_id))
            except KeyError:
                actions = []
        return ActivityOut(
            id=entry.id,
            time=entry.time,
            item_id=entry.item_id,
            step=entry.step.value,
            outcome=entry.outcome,
            file=entry.file,
            detail=entry.detail,
            actions=actions,
        )

    def item_out(item: Item) -> ItemOut:
        return ItemOut(id=item.id, state=item.state)

    # -- routes --------------------------------------------------------------------------------

    @app.get("/healthz")
    def healthz() -> Health:
        return Health(status="ok", version=__version__, reader=settings.reader)

    @app.get("/v1/activity")
    def activity(
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        before: Annotated[int | None, Query(ge=1)] = None,
    ) -> list[ActivityOut]:
        entries = state.activity.entries(limit, before)
        newest = newest_entry_ids(entries)
        return [activity_out(e, newest) for e in entries]

    @app.get("/v1/inbox/progress")
    def progress() -> ProgressOut:
        return ProgressOut(**dataclasses.asdict(state.worker.progress()))

    @app.get("/v1/needs-a-look")
    def needs_a_look() -> list[NeedsALookOut]:
        out: list[NeedsALookOut] = []
        for item in state.store.items(["asked"]):
            question = live_question(item)
            if question is None:
                continue
            out.append(
                NeedsALookOut(
                    id=item.id,
                    name=item.original_name,
                    file=item.rel_path,
                    reasons=[r.value for r in item.reasons],
                    question=question_out(question),
                    since=item.updated_at,
                )
            )
        return out

    @app.post("/v1/needs-a-look/answer-many")
    def answer_many(body: AnswerManyIn) -> list[ItemOut]:
        return [item_out(i) for i in state.actions.answer_many(body.item_ids, body.value)]

    @app.post("/v1/needs-a-look/{item_id}/answer")
    def answer(item_id: int, body: AnswerIn) -> ItemOut:
        item = known_item(item_id)
        discards = body.kind == "discard" or (body.kind == "copy" and body.value == "discard")
        is_copy = any(r in item.reasons for r in _COPY_REASONS)
        if discards and not is_copy and item.rel_path is not None and not body.confirm:
            raise AnswerError(ONLY_COPY)
        return item_out(state.actions.answer(item_id, body.kind, body.value, body.field))

    @app.post("/v1/needs-a-look/{item_id}/unlock")
    def unlock(item_id: int, body: UnlockIn) -> ItemOut:
        known_item(item_id)
        return item_out(
            state.actions.unlock(item_id, body.password, body.save, body.master_password)
        )

    @app.post("/v1/needs-a-look/{item_id}/undo")
    def undo_item(item_id: int) -> ItemOut:
        known_item(item_id)
        return item_out(state.actions.undo_item(item_id))

    @app.post("/v1/documents/{doc_id}/undo")
    def undo_document(doc_id: str) -> ItemOut:
        known_document(doc_id)
        return item_out(state.actions.undo_document(doc_id))

    @app.post("/v1/items/{item_id}/retry")
    def retry(item_id: int) -> ItemOut:
        known_item(item_id)
        return item_out(state.actions.retry(item_id))

    @app.get("/v1/documents/{doc_id}")
    def document(doc_id: str) -> DocumentOut:
        doc = known_document(doc_id)
        return DocumentOut(
            id=doc.id,
            item_id=doc.item_id,
            doc_type=doc.doc_type.value,
            owner=doc.owner,
            area=doc.area,
            rel_path=doc.rel_path,
            doc_date=doc.doc_date,
            date_source=doc.date_source,
            description=doc.description,
            fields=doc.fields,
            issues=doc.issues,
            created_at=doc.created_at,
        )

    @app.get("/v1/documents/{doc_id}/file")
    def document_file(doc_id: str) -> Response:
        return serve(known_document(doc_id).rel_path)

    @app.get("/v1/items/{item_id}/file")
    def item_file(item_id: int) -> Response:
        return serve(known_item(item_id).rel_path)

    @app.post("/v1/cards")
    async def upload_card(
        front: UploadFile,
        master_password: Annotated[str, Form()],
        back: UploadFile | None = None,
    ) -> CardOut:
        photos: list[bytes] = []
        for part in (front, back):
            if part is None or (part is back and not part.filename):
                continue
            data = await part.read(MAX_UPLOAD_BYTES + 1)
            if len(data) > MAX_UPLOAD_BYTES:
                raise HTTPException(413, TOO_LARGE)
            photos.append(data)
        result = await run_in_threadpool(state.cards.upload, photos, master_password)
        if isinstance(result, DocumentRecord):
            return CardOut(status="filed", document_id=result.id)
        return CardOut(status=result.state, item_id=result.id)

    @app.post("/v1/secrets/create")
    def secrets_create(body: MasterPasswordIn) -> dict[str, str]:
        if state.vault.exists(SECRETS_FILE):
            raise AnswerError(SECRETS_EXIST)
        if any(_is_syncing(e.name) for e in state.vault.list_root()):
            raise AnswerError(SECRETS_SYNCING)
        if state.store.count_documents_with_secrets() > 0:
            raise AnswerError(SECRETS_MISSING)
        try:
            state.gate.create(body.master_password)
        except FileExistsError:
            raise AnswerError(SECRETS_EXIST) from None
        return {"status": "created"}

    @app.post("/v1/secrets/unlock")
    def secrets_unlock(body: MasterPasswordIn) -> dict[str, str]:
        state.gate.unlock(body.master_password)
        return {"status": "unlocked"}

    @app.get("/v1/emergency-sheet")
    def emergency_sheet() -> HTMLResponse:
        return HTMLResponse(sheet_html(state.vault.root, state.worker.clock().date()))

    return app
