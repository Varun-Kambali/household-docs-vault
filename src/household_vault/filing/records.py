"""The record JSON: one file per filed document in `_system/records/`, the source of truth the
database can be rebuilt from (ADR 0006).

A record holds the fields, the page text and the filing decision, never a secret: secret
fields are None, card numbers live only in the password database (`secret_ref`), and every line
of text is stored after `mask_card_numbers`. Floats are rounded so the leak scan does not read
a long fraction as a number. `filer.py` imports this module, never the other way round.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, JsonValue, TypeAdapter, field_validator

from household_vault.db import DocumentRow, Item
from household_vault.doctypes import DocType
from household_vault.filing.decide import Decision, base_field
from household_vault.filing.names import DEFAULT_NAME, scrub_identifiers
from household_vault.reading.lines import Line, PageText
from household_vault.reading.pipeline import Reading
from household_vault.schemas import SCHEMAS
from household_vault.schemas._coerce import secret_fields
from household_vault.schemas.parse import mask_card_numbers, mask_card_shapes
from household_vault.vaultroot import RECORDS, VaultRoot

RECORD_VERSION: Literal[1] = 1

BOX_DIGITS = 4
CONFIDENCE_DIGITS = 3
SECONDS_DIGITS = 1
FIELD_DIGITS = 4

# Types whose text is masked for every long digit run: a card, or a page of unknown type.
LONG_RUN_TYPES = frozenset({None, DocType.card_front, DocType.other})
# A card's letter or statement: every 13 to 19 digit run is masked, but amounts and dates stay.
CARD_AREA_TYPES = frozenset({DocType.card_statement, DocType.card_welcome_letter})
_DIGITS = re.compile(r"\d+")
# On a card or unknown page every run of 3 or more digits goes, except the last four of a masked
# card number (just after an X) and a month and year (MM/YY, MM/YYYY).
_DATE_OR_RUN = re.compile(r"(?<!\d)(?:0[1-9]|1[0-2])/(?:\d{4}|\d{2})(?!\d)|\d{3,}")
# A secret value this short is a CVV or a PIN, kept out of text by exact match; a longer one
# is a card number, which `mask_card_numbers` handles and keeps the last four of.
_SECRET_RUN_LENGTHS = range(3, 13)

_DECISION = TypeAdapter(Decision)


def _round_floats(value: Any, digits: int = FIELD_DIGITS) -> Any:
    if isinstance(value, float):
        return round(value, digits)
    if isinstance(value, list):
        return [_round_floats(v, digits) for v in value]
    if isinstance(value, dict):
        return {k: _round_floats(v, digits) for k, v in value.items()}
    return value


def _round_line(line: Line) -> Line:
    return line.model_copy(
        update={
            "bbox": tuple(round(x, BOX_DIGITS) for x in line.bbox),
            "confidence": None
            if line.confidence is None
            else round(line.confidence, CONFIDENCE_DIGITS),
        }
    )


class RecordPage(BaseModel):
    page: int
    width: int
    height: int
    lines: list[Line]

    @field_validator("lines")
    @classmethod
    def _rounded(cls, lines: list[Line]) -> list[Line]:
        return [_round_line(ln) for ln in lines]


class RecordReading(BaseModel):
    engine: str
    prompt_version: str
    seconds: dict[str, float]

    @field_validator("seconds")
    @classmethod
    def _rounded(cls, seconds: dict[str, float]) -> dict[str, float]:
        return {k: round(v, SECONDS_DIGITS) for k, v in seconds.items()}


class DocumentRecord(BaseModel):
    record_version: Literal[1] = RECORD_VERSION
    id: str
    item_id: int
    original_name: str
    origin: Literal["inbox", "upload"]
    doc_type: DocType
    owner: str
    linked_people: list[str]
    area: str
    rel_path: str
    sha256: str
    doc_date: date
    date_source: Literal["document", "received"]
    description: str
    fields: dict[str, JsonValue]
    issues: dict[str, str]
    secret_ref: str | None
    pages: list[RecordPage]
    reading: RecordReading
    created_at: datetime

    @field_validator("fields")
    @classmethod
    def _rounded(cls, fields: dict[str, JsonValue]) -> dict[str, JsonValue]:
        rounded: dict[str, JsonValue] = _round_floats(fields)
        return rounded


def decision_to_json(decision: Decision) -> dict[str, Any]:
    """A decision as plain JSON, to keep in the item row while a filing is under way."""
    out: dict[str, Any] = _DECISION.dump_python(decision, mode="json")
    return out


def decision_from_json(data: Mapping[str, Any]) -> Decision:
    return _DECISION.validate_python(dict(data))


def mask_digit_runs(text: str) -> str:
    """Every run of 3 or more digits as X, for a card or unknown page, where a CVV or a glued
    number may sit in a line no field names. Kept: the last four of an already masked card
    number (a run of at most four digits straight after an X) and MM/YY or MM/YYYY."""

    def sub(match: re.Match[str]) -> str:
        run = match.group()
        if "/" in run:
            return run
        before = text[max(0, match.start() - 2) : match.start()]
        if len(run) <= 4 and (before.endswith("X") or before in ("X ", "X-")):
            return run
        return "X" * len(run)

    return _DATE_OR_RUN.sub(sub, text)


def stored_reading(reading: Reading, *, card_item: bool = False) -> dict[str, Any]:
    """The reading as the database and the record keep it: line text with card numbers masked
    (for a card, an unknown type or `other`: every 13 to 19 digit run, then every run of 3 or more
    digits except a masked number's last four and MM/YY dates), floats rounded. The
    secret values and the models' raw answers are never in a dump, so they are not here."""
    long_run = card_item or reading.doc_type in LONG_RUN_TYPES
    secret_runs = {
        digits
        for value in reading.secret_values.values()
        if (digits := "".join(c for c in value if c.isdigit()))
        and len(digits) in _SECRET_RUN_LENGTHS
    }

    def hide(match: re.Match[str]) -> str:
        return "X" * len(match.group()) if match.group() in secret_runs else match.group()

    def mask(text: str) -> str:
        if secret_runs:
            text = _DIGITS.sub(hide, text)
        if reading.doc_type in CARD_AREA_TYPES:
            text = mask_card_shapes(text)
        else:
            text = mask_card_numbers(text, any_long_run=long_run)
        return mask_digit_runs(text) if long_run else text

    dump: dict[str, Any] = reading.model_dump(mode="json")
    for page in dump["pages"]:
        for ln in page["lines"]:
            ln["text"] = mask(ln["text"])
            ln["bbox"] = [round(x, BOX_DIGITS) for x in ln["bbox"]]
            if ln["confidence"] is not None:
                ln["confidence"] = round(ln["confidence"], CONFIDENCE_DIGITS)
    dump["seconds"] = {k: round(v, SECONDS_DIGITS) for k, v in dump["seconds"].items()}
    dump["fields"] = _round_floats(dump["fields"])
    dump["issues"] = {k: mask(v) for k, v in dump["issues"].items()}
    return dump


def check_extra_fields(doc_type: DocType, extra: Mapping[str, JsonValue]) -> None:
    """Only a field of the type's schema, or `last4`, may be added to a record by the caller."""
    schema = SCHEMAS.get(doc_type)
    allowed = {"last4", *(schema.model_fields if schema else ())}
    unknown = sorted(set(extra) - allowed)
    if unknown:
        raise ValueError(f"not a field of {doc_type.value}: {', '.join(unknown)}")


def build_record(
    item: Item,
    stored: Mapping[str, Any],
    decision: Decision,
    rel_path: str,
    secret_ref: str | None,
    now: datetime,
    extra_fields: Mapping[str, JsonValue] | None = None,
    *,
    doc_id: str | None = None,
    sha256: str | None = None,
) -> DocumentRecord:
    """The record of a document about to be filed at `rel_path`.

    `stored` is `stored_reading`'s output, so a record can only hold masked line text. The
    owner's answers (`item.overrides`) replace the type, the fields and the issues of the read
    fields as `decide` applied them. `doc_id` and `sha256` default to a new id and the item's
    hash; a restart passes the ones it saved so the record is the same file as before.
    """
    ov = item.overrides
    raw_type = ov.get("doc_type") or stored.get("doc_type")
    if raw_type is None:
        raise ValueError("a document without a type cannot be filed")
    doc_type = DocType(raw_type)
    if decision.owner is None or decision.area is None:
        raise ValueError("a decision that asks a question has nothing to file")
    override_fields: dict[str, JsonValue] = dict(ov.get("fields") or {})
    check_extra_fields(doc_type, extra_fields or {})
    fields: dict[str, JsonValue] = {
        **(stored.get("fields") or {}),
        **override_fields,
        **(extra_fields or {}),
    }
    schema = SCHEMAS.get(doc_type)
    for name in secret_fields(schema) if schema else ():
        if name in fields:
            fields[name] = None
    overridden = {base_field(k) for k in override_fields}
    issues = {
        k: v for k, v in (stored.get("issues") or {}).items() if base_field(k) not in overridden
    }
    return DocumentRecord(
        id=doc_id or uuid.uuid4().hex,
        item_id=item.id,
        original_name=scrub_identifiers(item.original_name) or DEFAULT_NAME,
        origin=item.origin,
        doc_type=doc_type,
        owner=decision.owner,
        linked_people=[p for p in decision.linked if p != decision.owner],
        area=str(decision.area.value),
        rel_path=rel_path,
        sha256=sha256 or item.sha256,
        doc_date=decision.doc_date,
        date_source=decision.date_source,
        description=decision.description,
        fields=fields,
        issues=issues,
        secret_ref=secret_ref,
        pages=[RecordPage.model_validate(p) for p in stored.get("pages", [])],
        reading=RecordReading(
            engine=stored.get("engine", ""),
            prompt_version=stored.get("prompt_version", ""),
            seconds=stored.get("seconds", {}),
        ),
        created_at=now,
    )


def record_path(doc_id: str) -> str:
    return f"{RECORDS}/{doc_id}.json"


def write_record(vault: VaultRoot, record: DocumentRecord) -> str:
    """Write the record atomically and return its vault path."""
    vault.mkdirs(RECORDS)
    rel = record_path(record.id)
    vault.write_atomic(rel, record.model_dump_json(indent=2).encode("utf-8"))
    return rel


def read_record(vault: VaultRoot, doc_id: str) -> DocumentRecord:
    return DocumentRecord.model_validate_json(vault.read_bytes(record_path(doc_id)))


def record_rows(
    record: DocumentRecord,
) -> tuple[DocumentRow, list[tuple[str, Literal["owner", "linked"]]], list[PageText]]:
    """Everything the database holds for the document, so it can be rebuilt from records. The
    owner has one row, as owner; `linked_people` never holds the owner."""
    row = DocumentRow(
        id=record.id,
        item_id=record.item_id,
        doc_type=record.doc_type,
        owner=record.owner,
        area=record.area,
        rel_path=record.rel_path,
        sha256=record.sha256,
        doc_date=record.doc_date,
        date_source=record.date_source,
        description=record.description,
        fields=dict(record.fields),
        issues=dict(record.issues),
        secret_ref=record.secret_ref,
        created_at=record.created_at,
    )
    people: list[tuple[str, Literal["owner", "linked"]]] = [(record.owner, "owner")]
    people += [(p, "linked") for p in record.linked_people if p != record.owner]
    pages = [
        PageText(page=p.page, width=p.width, height=p.height, lines=list(p.lines))
        for p in record.pages
    ]
    return row, people, pages
