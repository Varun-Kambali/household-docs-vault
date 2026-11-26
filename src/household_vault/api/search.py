"""Search routes. A quick search runs no model; a full one reads the prompt first. Nothing here
logs, stores or echoes a prompt: it lives in the request and is gone.
"""

from collections.abc import Iterable
from datetime import date

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from household_vault.api.models import (
    AnswerOut,
    ChoiceOut,
    LineRefOut,
    ListIn,
    ListOut,
    NoAnswerOut,
    PartOut,
    PersonOut,
    QueryOut,
    RowOut,
    SearchIn,
    SearchOut,
    SentenceOut,
)
from household_vault.app_state import AppState
from household_vault.doctypes import DocType
from household_vault.reading.ollama import ModelUnavailable
from household_vault.schemas import SCHEMAS
from household_vault.schemas._coerce import field_kind
from household_vault.search.answer import Answer, NoAnswer, compose
from household_vault.search.query import Query, read_prompt, resolve
from household_vault.search.retrieve import LineRef, Row
from household_vault.search.sentence import Sentence, apply_part, render, sentence

BAD_CHANGE = "That change is not one the sentence offers."


def drive_path(prefix: str, rel_path: str) -> str:
    return f"{prefix.rstrip('/')}/{rel_path}" if prefix else rel_path


def line_out(ref: LineRef) -> LineRefOut:
    return LineRefOut(page=ref.page, idx=ref.idx, bbox=ref.bbox)


def kinds_of(doc_type: DocType, names: Iterable[str]) -> dict[str, str]:
    schema = SCHEMAS.get(doc_type)
    return {
        name: field_kind(schema, name) if schema and name in schema.model_fields else "text"
        for name in names
    }


def row_out(row: Row, prefix: str) -> RowOut:
    return RowOut(
        document_id=row.document_id,
        doc_type=row.doc_type.value,
        owner=row.owner,
        people=row.people,
        area=row.area,
        rel_path=row.rel_path,
        drive_path=drive_path(prefix, row.rel_path),
        doc_date=row.doc_date,
        key_fields=row.key_fields,
        field_kinds=kinds_of(row.doc_type, row.key_fields),
        date=row.date,
        score=row.score,
        lines=[line_out(r) for r in row.lines],
    )


def sentence_out(value: Sentence) -> SentenceOut:
    return SentenceOut(
        parts=[
            PartOut(
                slot=p.slot,
                text=p.text,
                value=p.value,
                options=[ChoiceOut(value=o.value, label=o.label) for o in p.options],
            )
            for p in value.parts
        ],
        text=render(value),
    )


def answer_out(answer: Answer) -> AnswerOut:
    return AnswerOut(
        text=answer.text,
        field=answer.field,
        value=answer.value,
        document_id=answer.document_id,
        page=answer.page,
        lines=[line_out(r) for r in answer.lines],
        masked=answer.masked,
    )


def add_search_routes(app: FastAPI, state: AppState) -> None:
    prefix = state.settings.drive_prefix

    def today() -> date:
        return state.worker.clock().date()

    def vectors() -> str:
        if state.vectors.embedder is None:
            return "off"
        return "stale" if state.vectors.stale() else "on"

    def rows_out(rows: list[Row]) -> list[RowOut]:
        return [row_out(r, prefix) for r in rows]

    @app.post("/v1/search")
    def search(body: SearchIn) -> SearchOut:
        prompt = body.prompt
        reading = "on" if state.prompt_reader is not None else "off"
        if body.full and state.prompt_reader is not None:
            try:
                parsed = read_prompt(prompt, state.prompt_reader)
            except ModelUnavailable:
                reading = "off"
            else:
                places = state.searcher.place_values()
                query = resolve(parsed, state.household, today(), prompt, places)
                if query.intent == "list":
                    return SearchOut(
                        rows=rows_out(state.searcher.list(query)),
                        query=QueryOut.model_validate(query),
                        sentence=sentence_out(sentence(query, state.household, today())),
                        reading="on",
                        vectors=vectors(),
                    )
                rows = state.searcher.lookup(query, prompt)
                outcome = compose(query, rows, state.store, today())
                return SearchOut(
                    rows=rows_out(rows),
                    query=QueryOut.model_validate(query),
                    answer=answer_out(outcome) if isinstance(outcome, Answer) else None,
                    no_answer=(
                        NoAnswerOut(reason=outcome.reason, closest=outcome.closest)
                        if isinstance(outcome, NoAnswer)
                        else None
                    ),
                    reading="on",
                    vectors=vectors(),
                )
        return SearchOut(
            rows=rows_out(state.searcher.quick(prompt)),
            reading=reading,
            vectors=vectors(),
        )

    @app.post("/v1/search/list", response_model=None)
    def search_list(body: ListIn) -> ListOut | JSONResponse:
        query: Query = body.query.to_query()
        if body.change is not None:
            try:
                query = apply_part(query, body.change.slot, body.change.value, today())
            except ValueError:
                return JSONResponse(status_code=422, content={"detail": BAD_CHANGE})
        return ListOut(
            rows=rows_out(state.searcher.list(query)),
            sentence=sentence_out(sentence(query, state.household, today())),
            query=QueryOut.model_validate(query),
        )

    @app.get("/v1/people")
    def people() -> list[PersonOut]:
        return [PersonOut(id=p.id, name=p.name) for p in state.household.people]
