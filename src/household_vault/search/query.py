"""A person's prompt, read into a structured query.

A small local model copies the words of the prompt into slots (people, types, field, date and
place phrases). Code then works out who the people are and what the dates mean, and reports
anything it could not read. The model sees only the prompt and the fixed vocabulary, never a
document, and never works out a date.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Literal, Protocol

from pydantic import AfterValidator, BaseModel, ConfigDict, ValidationError, WithJsonSchema

from household_vault.doctypes import Area, DocType
from household_vault.people import Household, match_person, normalise_name
from household_vault.reading.engines import prefill_for
from household_vault.reading.ollama import ModelError, ModelUnavailable, OllamaClient
from household_vault.search.dates import DateRange, parse_date_phrase
from household_vault.search.vocab import (
    AREA_LABELS,
    DATE_ROLES,
    FIELD_LABELS,
    TYPE_WORDS,
    DateRole,
)


def _askable(value: str) -> str:
    if value not in FIELD_LABELS:
        raise ValueError("not a field a question can ask for")
    return value


# A plain string checked against the field keys, with the keys listed as an enum in the JSON
# schema sent to Ollama. (A `Literal` made from a dict's keys cannot be typed for mypy.)
AskField = Annotated[
    str,
    AfterValidator(_askable),
    WithJsonSchema({"type": "string", "enum": list(FIELD_LABELS)}),
]


class DateSlot(BaseModel):
    role: DateRole | None
    phrase: str


class QueryReading(BaseModel):
    """What the model copies out of a prompt. Its JSON schema is the `format` sent to Ollama."""

    intent: Literal["lookup", "list", "find"]
    people: list[str]
    types: list[DocType]
    areas: list[Area]
    field: AskField | None
    date: DateSlot | None
    place: str | None
    words: str


class Query(BaseModel):
    """A reading with people and dates worked out by code. Also the list route's body."""

    model_config = ConfigDict(frozen=True)

    intent: Literal["lookup", "list", "find"]
    people: list[str] = []  # person ids, `home` included; empty means everyone
    types: list[DocType] = []
    areas: list[Area] = []
    field: str | None = None
    role: DateRole | None = None
    range: DateRange | None = None
    place: str | None = None
    words: str = ""
    unread: list[str] = []  # parts code could not resolve, such as "person: Anil"


def _system_text() -> str:
    types = "\n".join(
        f"- {t.value}: {', '.join(words)}" for t, words in TYPE_WORDS.items() if words
    )
    areas = "\n".join(f"- {a.value}: {label}" for a, label in AREA_LABELS.items())
    fields = "\n".join(f"- {key}: {label}" for key, label in FIELD_LABELS.items())
    roles = sorted({r for per_type in DATE_ROLES.values() for r in per_type})
    head = (
        "You read one question about a family's filed documents into JSON. Fill the slots from "
        "the question. Copy person, time and place words exactly as written; never work out a "
        "date.\n\n"
        'intent: "lookup" when the question asks for one value of one document (a number, an '
        'expiry, an amount); "list" when it asks for every document that matches a condition; '
        '"find" for anything else.\n'
        'people: the names or relations written in the question, as written ("Ravi", "my wife", '
        '"everyone"). Empty when none.\n'
        "types: document types the question is about, from the list below. Empty when unsure.\n"
        "areas: folder areas the question is about, from the list below. Empty when unsure.\n"
        "field: the one value being asked for, from the list below, only for a lookup. null "
        "otherwise.\n"
        "date: when the question has a time condition. role is what the date is about, one of "
        f"{', '.join(roles)}, or null; phrase is the time words as written "
        '("before March", "this year", "FY 2025-26").\n'
        "place: a shop, insurer, hospital or other place named in the question, as written. "
        "null when none.\n"
        'words: the other words worth searching for, such as a product ("fridge").\n\n'
    )
    return (
        f"{head}Document types (type: words people use):\n{types}\n\n"
        f"Areas:\n{areas}\n\nFields (field: label):\n{fields}"
    )


PROMPT_READ_V1 = _system_text()


class PromptReader(Protocol):
    name: str

    def read(self, prompt: str) -> str:
        """The model's JSON text for a prompt."""
        ...


class OllamaPromptReader:
    def __init__(self, client: OllamaClient, model: str) -> None:
        self._client = client
        self._model = model
        self.name = f"ollama:{model}"

    def read(self, prompt: str) -> str:
        return self._client.chat_json(
            self._model,
            PROMPT_READ_V1,
            prompt,
            [],
            QueryReading.model_json_schema(),
            prefill_for(self._model),
            options={"num_ctx": 4096, "num_predict": 400},
        )


def read_prompt(prompt: str, reader: PromptReader) -> QueryReading:
    """One retry on JSON that fails the schema, then plain keywords. A model that is off or
    failing raises `ModelUnavailable`, so the caller can say the reading is off. The prompt is
    never logged and never put in an error."""
    for _ in range(2):
        try:
            raw = reader.read(prompt)
        except (ModelUnavailable, ModelError) as exc:
            raise ModelUnavailable("the prompt reading is off") from exc
        try:
            return QueryReading.model_validate_json(raw)
        except ValidationError:
            continue
    return QueryReading(
        intent="find",
        people=[],
        types=[],
        areas=[],
        field=None,
        date=None,
        place=None,
        words=prompt,
    )


_POSSESSIVE = re.compile(r"['\u2019]s$")
_EVERYONE = {"everyone", "all", "family", "us", "me", "my", "i"}
_HOME = {"home", "house"}
_FORWARD_ROLES = {"expiry", "renewal", "due"}


def _first_word_owner(phrase: str, household: Household) -> str | None:
    words = phrase.split()
    if len(words) != 1:
        return None
    owners = {
        person.id
        for person in household.people
        for name in (person.name, *person.aliases)
        if normalise_name(name).split()[:1] == words
    }
    return next(iter(owners)) if len(owners) == 1 else None


def _person(phrase: str, household: Household) -> tuple[str | None, bool]:
    """(person id or None, whether the phrase means no filter)."""
    text = _POSSESSIVE.sub("", phrase.strip().lower())
    if text in _EVERYONE:
        return None, True
    if text in _HOME:
        return "home", False
    pid = match_person(text, household).person_id or _first_word_owner(
        normalise_name(text), household
    )
    return pid, False


def resolve(reading: QueryReading, household: Household, today: date) -> Query:
    unread: list[str] = []
    people: list[str] = []
    for phrase in reading.people:
        pid, no_filter = _person(phrase, household)
        if pid is not None:
            if pid not in people:
                people.append(pid)
        elif not no_filter:
            unread.append(f"person: {phrase}")
    role: DateRole | None = None
    span: DateRange | None = None
    if reading.date is not None:
        role = reading.date.role
        span = parse_date_phrase(reading.date.phrase, today)
        if span is not None and role in _FORWARD_ROLES and span.start is None and span.end:
            # a forward question looks ahead: an end only means "from today to then"
            span = DateRange(start=today, end=span.end)
        if span is None or (span.start and span.end and span.start > span.end):
            span = None  # never an inverted range
            unread.append(f"date: {reading.date.phrase}")
    return Query(
        intent=reading.intent,
        people=people,
        types=reading.types,
        areas=reading.areas,
        field=reading.field,
        role=role,
        range=span,
        place=reading.place,
        words=reading.words,
        unread=unread,
    )
