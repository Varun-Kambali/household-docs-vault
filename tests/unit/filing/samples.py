"""Shared sample data for the record and filer tests: one health policy for p1."""

from datetime import date, datetime
from typing import Any

from household_vault.db import Item
from household_vault.doctypes import Area, DocType
from household_vault.filing.decide import Decision
from household_vault.reading.lines import Line, PageText
from household_vault.reading.pipeline import Reading

NOW = datetime(2026, 11, 20, 9, 0).astimezone()

DECISION = Decision(
    outcome="file",
    reasons=[],
    owner="p1",
    linked=["p1", "p3"],
    area=Area.insurance,
    folder="Ravi Kumar Rao/Insurance",
    doc_date=date(2026, 4, 1),
    date_source="document",
    description="Health policy - Star Health",
    possible_copy_of=None,
    printed_names={},
    last4=None,
)

ITEM = Item(
    id=1,
    sha256="a" * 64,
    original_name="policy.pdf",
    origin="inbox",
    rel_path="Inbox/policy.pdf",
    target=None,
    pending=None,
    kind="pdf",
    state="reading",
    reasons=[],
    question=None,
    reading=None,
    overrides={},
    document_id=None,
    created_at=NOW,
    updated_at=NOW,
)


def reading_with_box(
    bbox: tuple[float, float, float, float] = (0.1, 0.1, 0.5, 0.2),
    *,
    text: str = "Star Health policy schedule",
    doc_type: DocType | None = DocType.health_policy,
    fields: dict[str, Any] | None = None,
    secret_values: dict[str, str] | None = None,
) -> Reading:
    page = PageText(
        page=0,
        width=600,
        height=800,
        lines=[Line(text=text, bbox=bbox, confidence=0.87654321)],
    )
    return Reading(
        pages=[page],
        english_letters=200,
        doc_type=doc_type,
        fields={"insurer": "Star Health", "policyholder": "Ravi Kumar Rao"}
        if fields is None
        else fields,
        issues={},
        seconds={"read": 1.2345, "fill": 12.3456},
        engine="stub",
        prompt_version="v2",
        secret_values=secret_values or {},
    )


READING = reading_with_box()


def card_reading(
    secret_values: dict[str, str] | None = None, line_text: str = "HDFC Bank"
) -> Reading:
    return reading_with_box(
        text=line_text,
        doc_type=DocType.card_front,
        fields={"bank": "HDFC Bank", "number": None},
        secret_values=secret_values,
    )
