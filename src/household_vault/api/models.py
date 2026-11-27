"""Request and response shapes. No response model has a field that can hold a secret."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    field_validator,
)

from household_vault.doctypes import Area, DocType
from household_vault.filing.questions import AnswerKind
from household_vault.search.dates import DateRange
from household_vault.search.query import Query
from household_vault.search.vocab import DateRole


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Health(BaseModel):
    status: str
    version: str
    reader: str


class OptionOut(BaseModel):
    value: str
    label: str


class QuestionOut(BaseModel):
    reason: str
    text: str
    answer_kind: str
    options: list[OptionOut]
    field: str | None = None


class ActivityOut(BaseModel):
    id: int
    time: datetime
    item_id: int | None
    step: str
    outcome: str
    file: str | None
    detail: str
    actions: list[str]
    # Set with `open` on a filed item: the document the viewer opens.
    document_id: str | None = None


class ProgressOut(BaseModel):
    waiting: int
    current: str | None
    step: str | None
    total_in_batch: int
    done_in_batch: int
    asked_in_batch: int
    batch_started_at: datetime | None


class NeedsALookOut(BaseModel):
    id: int
    name: str
    file: str | None
    reasons: list[str]
    question: QuestionOut
    since: datetime


class AnswerIn(Strict):
    kind: AnswerKind
    value: str = ""
    field: str | None = None
    # Discarding a file that is not a copy deletes the only copy. The screen asks first and
    # then sends this flag.
    confirm: bool = False


class AnswerManyIn(Strict):
    item_ids: list[int] = Field(min_length=1, max_length=500)
    value: str


class UnlockIn(Strict):
    password: str
    save: bool = False
    master_password: str | None = None


class MasterPasswordIn(Strict):
    master_password: str


class SecretsStatusOut(BaseModel):
    exists: bool
    unlocked: bool


class ItemOut(BaseModel):
    id: int
    state: str


class CardOut(BaseModel):
    status: str
    document_id: str | None = None
    item_id: int | None = None


class DocumentOut(BaseModel):
    id: str
    item_id: int
    doc_type: str
    owner: str
    area: str
    rel_path: str
    doc_date: date
    date_source: str
    description: str
    fields: dict[str, Any]
    issues: dict[str, Any]
    created_at: datetime
    drive_path: str
    people: list[str]
    field_kinds: dict[str, str]
    page_count: int


# -- search ---------------------------------------------------------------------------------------

MAX_PROMPT = 300


class SearchIn(Strict):
    prompt: str
    full: bool = False
    # A reading the screen already holds, with one part of its sentence changed: runs again
    # without reading the prompt a second time.
    query: QueryIn | None = None
    change: PartChange | None = None

    @field_validator("prompt")
    @classmethod
    def _length(cls, value: str) -> str:
        value = value.strip()
        if not 1 <= len(value) <= MAX_PROMPT:
            raise ValueError("a prompt is 1 to 300 characters")
        return value


class LineRefOut(BaseModel):
    page: int
    idx: int
    bbox: tuple[float, float, float, float]


class RowOut(BaseModel):
    document_id: str
    doc_type: str
    owner: str
    people: list[str]
    area: str
    rel_path: str
    drive_path: str
    doc_date: date
    key_fields: dict[str, JsonValue]
    field_kinds: dict[str, str]
    date: date | None
    score: float
    lines: list[LineRefOut]


class QueryIn(Strict):
    """A query as the screen sends it back: the same shape the search returned."""

    intent: Literal["lookup", "list", "find"]
    people: list[Annotated[str, StringConstraints(max_length=64)]] = Field(
        default=[], max_length=20
    )
    types: list[DocType] = Field(default=[], max_length=len(DocType))
    areas: list[Area] = Field(default=[], max_length=len(Area))
    field: str | None = Field(default=None, max_length=64)
    role: DateRole | None = None
    range: DateRange | None = None
    place: str | None = Field(default=None, max_length=MAX_PROMPT)
    words: str = Field(default="", max_length=MAX_PROMPT)
    unread: list[Annotated[str, StringConstraints(max_length=MAX_PROMPT)]] = Field(
        default=[], max_length=20
    )

    def to_query(self) -> Query:
        return Query(**self.model_dump())


QueryOut = Query


class PartChange(Strict):
    slot: str = Field(max_length=16)
    value: JsonValue = None

    @field_validator("value")
    @classmethod
    def _bounded(cls, value: JsonValue) -> JsonValue:
        items = value if isinstance(value, list) else [value]
        if len(items) > 20 or any(isinstance(i, str) and len(i) > MAX_PROMPT for i in items):
            raise ValueError("a part value is short")
        return value


SearchIn.model_rebuild()


class ChoiceOut(BaseModel):
    value: JsonValue
    label: str


class PartOut(BaseModel):
    slot: str
    text: str
    value: JsonValue
    options: list[ChoiceOut]


class SentenceOut(BaseModel):
    parts: list[PartOut]
    text: str


class AnswerOut(BaseModel):
    text: str
    field: str
    value: JsonValue
    document_id: str
    page: int
    lines: list[LineRefOut]
    masked: bool


class NoAnswerOut(BaseModel):
    reason: Literal["no_documents", "unknown_person", "weak_match", "no_field", "not_on_page"]
    closest: list[str]


class SearchOut(BaseModel):
    rows: list[RowOut]
    query: QueryOut | None = None
    sentence: SentenceOut | None = None
    answer: AnswerOut | None = None
    no_answer: NoAnswerOut | None = None
    reading: Literal["on", "off"]
    vectors: Literal["on", "off", "stale"]


class ListIn(Strict):
    query: QueryIn
    change: PartChange | None = None


class ListOut(BaseModel):
    rows: list[RowOut]
    sentence: SentenceOut
    query: QueryOut


class PersonOut(BaseModel):
    id: str
    name: str


class LineOut(BaseModel):
    idx: int
    text: str
    bbox: tuple[float, float, float, float]


class PageLinesOut(BaseModel):
    page: int
    lines: list[LineOut]
