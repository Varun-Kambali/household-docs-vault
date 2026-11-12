"""Ground-truth records for synthetic documents."""

from typing import Literal

from pydantic import BaseModel

from household_vault.doctypes import DocType

Lang = Literal["en", "kn", "hi"]


class LineBox(BaseModel):
    text: str
    page: int
    # (x0, y0, x1, y1) as fractions of the page, origin top-left
    bbox: tuple[float, float, float, float]
    lang: Lang


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
