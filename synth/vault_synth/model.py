"""Ground-truth records for synthetic documents."""

from typing import Literal

from pydantic import BaseModel, JsonValue

from household_vault.doctypes import DocType
from household_vault.reading.lines import Line

# the one line shape lives in src; synth keeps its old name for it
Lang = Literal["en", "kn", "hi"]


LineBox = Line


class SynthDoc(BaseModel):
    """One document file set and what is true about it.

    Version 2. A spike-v0 truth file still parses: the new fields have defaults, and its field
    values are plain text.
    """

    doc_id: str
    base_id: str
    doc_type: DocType
    person: str
    variant: Literal["clean", "photo", "scan", "locked"]
    files: list[str]
    # eval-v1: every schema field, typed, and None where the page does not print it
    fields: dict[str, JsonValue]
    # only the fields that are not None appear in `printed` and `field_lines`
    printed: dict[str, str]
    lines: list[LineBox]
    field_lines: dict[str, list[int]]
    set_name: str = "spike-v0"
    split: Literal["train", "val", "test"] | None = None
    # "home", a household person id, or None when the app has to ask
    owner: str | None = None
    linked_people: list[str] = []
    area: str | None = None
    folder: str | None = None
    # Reason values the app should raise for this document
    expected_ask: list[str] = []
    password: str | None = None
