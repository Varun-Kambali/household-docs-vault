"""Request and response shapes. No response model has a field that can hold a secret."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from household_vault.filing.questions import AnswerKind


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
