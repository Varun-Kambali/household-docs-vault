"""Decide where a document goes: whose it is, who it links to, its folder, its date, its
description, and whether to ask instead. Pure: nothing here reads or writes a file."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from pydantic import JsonValue

from household_vault.db import DocumentRow
from household_vault.doctypes import (
    AREA,
    COPY_KEY,
    DATE_FIELD,
    OWNER,
    REQUIRED,
    Area,
    DocType,
)
from household_vault.filing.names import describe, folder_for
from household_vault.people import Household, match_person
from household_vault.reading.pipeline import Reading
from household_vault.reasons import PRIORITY, Reason
from household_vault.schemas import SCHEMAS
from household_vault.schemas._coerce import field_kind
from household_vault.scoring import normalise


@dataclass(frozen=True)
class Overrides:
    """What the owner of the vault said when asked. They replace the read values before the
    rules run."""

    doc_type: DocType | None = None
    owner: str | None = None
    fields: dict[str, JsonValue] = field(default_factory=dict)
    keep_copy: bool = False


@dataclass(frozen=True)
class Decision:
    outcome: Literal["file", "ask"]
    reasons: list[Reason]
    owner: str | None
    linked: list[str]
    area: Area | None
    folder: str | None
    doc_date: date
    date_source: Literal["document", "received"]
    description: str
    possible_copy_of: str | None
    printed_names: dict[str, str]
    last4: str | None


def base_field(issue_key: str) -> str:
    """`medicines[1]` (one bad item of a list field) names the field `medicines`."""
    return issue_key.split("[", 1)[0]


def _present(value: object) -> bool:
    return value is not None and value != "" and value != []


def required_problems(
    doc_type: DocType,
    fields: Mapping[str, JsonValue],
    issues: Mapping[str, str],
    secret_values: Mapping[str, str],
) -> tuple[list[str], list[str]]:
    """The required fields that were not read, as (missing, with an issue), in schema order.
    A field held in `secret_values` was read; it is only kept out of `fields`."""
    schema = SCHEMAS.get(doc_type)
    order = list(schema.model_fields) if schema else []
    names = sorted(REQUIRED.get(doc_type, ()), key=lambda n: order.index(n) if n in order else 99)
    issued = {base_field(k) for k in issues if k != "_json"}
    missing: list[str] = []
    with_issue: list[str] = []
    for name in names:
        if _present(fields.get(name)) or name in secret_values:
            continue
        if doc_type is DocType.card_front and name == "number":
            continue  # a card without a readable number is `card_unreadable`, never typed in
        (with_issue if name in issued else missing).append(name)
    return missing, with_issue


def _names(value: JsonValue | None) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str) and v.strip()]
    return []


def _last4(secret_values: Mapping[str, str]) -> str | None:
    digits = "".join(c for c in secret_values.get("number", "") if c.isdigit())
    return digits[-4:] if len(digits) >= 4 else None


def _document_date(doc_type: DocType | None, fields: Mapping[str, JsonValue]) -> date | None:
    name = DATE_FIELD.get(doc_type) if doc_type else None
    value = fields.get(name) if name else None
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


def _key_value(
    doc_type: DocType, name: str, fields: Mapping[str, JsonValue], last4: str | None = None
) -> str | None:
    """One copy-key value in its comparison form, or None when it was not read. A card's
    last4 comes from its number (the reading) or from its stored fields (a filed card)."""
    value = fields.get(name)
    if doc_type is DocType.card_front and name == "last4" and last4 is not None:
        value = last4
    if not _present(value):
        return None
    schema = SCHEMAS.get(doc_type)
    kind = field_kind(schema, name) if schema and name in schema.model_fields else "identifier"
    return normalise(kind, str(value))


def _possible_copy(
    doc_type: DocType,
    fields: Mapping[str, JsonValue],
    last4: str | None,
    filed: Sequence[DocumentRow],
) -> str | None:
    keys = COPY_KEY.get(doc_type, ())
    if not keys:
        return None
    mine = [_key_value(doc_type, k, fields, last4) for k in keys]
    if any(v is None for v in mine):
        return None
    for row in filed:
        if row.doc_type == doc_type and [_key_value(doc_type, k, row.fields) for k in keys] == mine:
            return row.id
    return None


def decide(
    reading: Reading,
    household: Household,
    received: date,
    filed: Sequence[DocumentRow],
    overrides: Overrides | None = None,
) -> Decision:
    ov = overrides or Overrides()
    if (
        ov.owner is not None
        and ov.owner != "home"
        and all(p.id != ov.owner for p in household.people)
    ):
        raise ValueError(f"the owner {ov.owner!r} is not in the household")
    doc_type = ov.doc_type or reading.doc_type
    fields: dict[str, JsonValue] = {**reading.fields, **ov.fields}
    overridden = {base_field(k) for k in ov.fields}
    issues = {k: v for k, v in reading.issues.items() if base_field(k) not in overridden}
    found: set[Reason] = set()
    printed: dict[str, str] = {}

    if doc_type is None:
        found.add(Reason.no_english)
    elif doc_type is DocType.other or (
        ov.doc_type is None
        and reading.type_check is not None
        and reading.type_check.verdict == "conflicts"
    ):
        found.add(Reason.type_unsure)
    if "_json" in reading.issues:
        found.add(Reason.read_failed)

    last4 = _last4(reading.secret_values) if doc_type is DocType.card_front else None
    owner: str | None = ov.owner
    linked: set[str] = set()
    area: Area | None = None
    folder: str | None = None
    if doc_type is not None and doc_type in AREA:
        rule = OWNER[doc_type]
        if owner is None:
            if rule.home:
                owner = "home"
            else:
                owner = _owner_from_fields(rule.owner_fields, fields, household, found, printed)
        for name in rule.linked_fields:
            for text in _names(fields.get(name)):
                person = match_person(text, household).person_id
                if person:
                    linked.add(person)
        if owner not in (None, "home"):
            linked.add(str(owner))
        missing, with_issue = required_problems(doc_type, fields, issues, reading.secret_values)
        if missing:
            found.add(Reason.missing_required)
        if with_issue:
            found.add(Reason.field_issue)
        if doc_type is DocType.card_front and last4 is None:
            found.add(Reason.card_unreadable)
        area = AREA[doc_type]
        if owner is not None:
            folder = folder_for(doc_type, owner, household)

    copy_of = None
    if doc_type is not None and doc_type in AREA and not ov.keep_copy:
        copy_of = _possible_copy(doc_type, fields, last4, filed)
        if copy_of:
            found.add(Reason.possible_copy)

    when = _document_date(doc_type, fields)
    description = describe(doc_type, fields, last4) if doc_type in AREA else "Document"
    reasons = [r for r in PRIORITY if r in found]
    return Decision(
        outcome="ask" if reasons else "file",
        reasons=reasons,
        owner=owner,
        linked=sorted(linked),
        area=area,
        folder=folder,
        doc_date=when or received,
        date_source="document" if when else "received",
        description=description,
        possible_copy_of=copy_of,
        printed_names=printed,
        last4=last4,
    )


def _owner_from_fields(
    owner_fields: tuple[str, ...],
    fields: Mapping[str, JsonValue],
    household: Household,
    found: set[Reason],
    printed: dict[str, str],
) -> str | None:
    """The first owner field with a name gives the owner: the first of its names (a list field
    has several) that matches one person. An unmatched name is `person_unknown`, a tie
    `person_unsure`; the printed name is kept for the question."""
    for name in owner_fields:
        texts = _names(fields.get(name))
        if not texts:
            continue
        tied: str | None = None
        for text in texts:
            match = match_person(text, household)
            if match.person_id:
                return match.person_id
            if match.candidates and tied is None:
                tied = text
        if tied is not None:
            found.add(Reason.person_unsure)
            printed[name] = tied
        else:
            found.add(Reason.person_unknown)
            printed[name] = texts[0]
        return None
    found.add(Reason.person_unknown)
    return None
