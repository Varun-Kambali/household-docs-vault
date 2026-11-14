"""Ground-truth records for synthetic documents."""

from typing import Literal

from pydantic import BaseModel

from household_vault.doctypes import DocType
from household_vault.reading.lines import Line

# the one line shape lives in src; synth keeps its old name for it
Lang = Literal["en", "kn", "hi"]


LineBox = Line


class SynthDoc(BaseModel):
    doc_id: str
    base_id: str
    doc_type: DocType
    person: str
    variant: Literal["clean", "photo"]
    files: list[str]
    fields: dict[str, str]
    printed: dict[str, str]
    lines: list[LineBox]
    field_lines: dict[str, list[int]]
