"""Search routes. A quick search runs no model; a full one reads the prompt first. Nothing here
logs, stores or echoes a prompt: it lives in the request and is gone.
"""

import re
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
from household_vault.checks import luhn_valid
from household_vault.doctypes import DocType
from household_vault.reading.ollama import ModelUnavailable
from household_vault.schemas import SCHEMAS
from household_vault.schemas._coerce import field_kind
from household_vault.search.answer import Answer, NoAnswer, compose
from household_vault.search.query import Query, read_prompt, resolve
from household_vault.search.retrieve import LineRef, Row
from household_vault.search.sentence import Sentence, apply_part, render, sentence

BAD_CHANGE = "That change is not one the sentence offers."


_CARD_RUN = re.compile(r"(?<![\d])\d(?:[ .\-/]?\d){12,18}(?![\d])")


def _between(digits: str, size: int, low: int, high: int) -> bool:
    return low <= int(digits[:size]) <= high


def card_shaped(digits: str) -> bool:
    """Luhn-valid, with the length and leading digits of a card brand. An IMEI (15 digits, Luhn
    valid) or a long policy number is not a card, so a search by it stays whole. checks.py has
    the Luhn check and the published test numbers but no brand ranges, so the ranges are here."""
    if not luhn_valid(digits):
        return False
    n = len(digits)
    return (
        (digits[0] == "4" and n in (13, 16, 19))  # Visa
        or (n == 16 and (_between(digits, 2, 51, 55) or _between(digits, 4, 2221, 2720)))
        or (n == 15 and digits[:2] in ("34", "37"))  # American Express
        or (n == 16 and (digits[:2] in ("60", "65", "81", "82") or digits[:3] == "508"))  # RuPay
        or (
            16 <= n <= 19
            and (digits[:4] == "6011" or digits[:2] == "65" or _between(digits, 3, 644, 649))
        )  # Discover
        or (  # Diners: 14 digits, and the 16 of the published test number
            14 <= n <= 19 and (digits[:2] in ("36", "38") or _between(digits, 3, 300, 305))
        )
        or (16 <= n <= 19 and _between(digits, 4, 3528, 3589))  # JCB
    )


def mask_card_runs(text: str) -> str:
    """A prompt is not a place for a card number: a card-shaped run of 13 to 19 digits (spaces,
    dashes, dots or slashes between digits) keeps only its last four, so neither the reading
    model nor the embedder sees the rest. Other long numbers, such as an IMEI, stay whole."""

    def hide(hit: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", hit.group())
        return f"\u2022\u2022\u2022\u2022 {digits[-4:]}" if card_shaped(digits) else hit.group()

    return _CARD_RUN.sub(hide, text)


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

    def full_out(query: Query, prompt: str) -> SearchOut:
        said = (
            sentence_out(sentence(query, state.household, today()))
            if query.intent != "find"
            else None
        )
        if query.intent == "list":
            return SearchOut(
                rows=rows_out(state.searcher.list(query)),
                query=QueryOut.model_validate(query),
                sentence=said,
                reading="on",
                vectors=vectors(),
            )
        rows = state.searcher.lookup(query, prompt)
        outcome = compose(query, rows, state.store, today())
        return SearchOut(
            rows=rows_out(rows),
            query=QueryOut.model_validate(query),
            sentence=said,
            answer=answer_out(outcome) if isinstance(outcome, Answer) else None,
            no_answer=(
                NoAnswerOut(reason=outcome.reason, closest=outcome.closest)
                if isinstance(outcome, NoAnswer)
                else None
            ),
            reading="on",
            vectors=vectors(),
        )

    @app.post("/v1/search", response_model=None, responses={200: {"model": SearchOut}})
    def search(body: SearchIn) -> SearchOut | JSONResponse:
        prompt = mask_card_runs(body.prompt)
        if body.query is not None:
            query: Query = body.query.to_query()
            if body.change is not None:
                try:
                    query = apply_part(query, body.change.slot, body.change.value, today())
                except ValueError:
                    return JSONResponse(status_code=422, content={"detail": BAD_CHANGE})
            return full_out(query, prompt)
        reading = "on" if state.prompt_reader is not None else "off"
        if body.full and state.prompt_reader is not None:
            try:
                parsed = read_prompt(prompt, state.prompt_reader)
            except ModelUnavailable:
                reading = "off"
            else:
                places = state.searcher.place_values()
                query = resolve(parsed, state.household, today(), prompt, places)
                return full_out(query, prompt)
        return SearchOut(
            rows=rows_out(state.searcher.quick(prompt)),
            reading=reading,
            vectors=vectors(),
        )

    @app.post("/v1/search/list", response_model=None, responses={200: {"model": ListOut}})
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
