"""Descriptions, file names and folders. Text from a document reaches a file name here, so
everything goes through `clean_component` and the vault's own name check."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from datetime import date

from pydantic import JsonValue

from household_vault.doctypes import AREA, AREA_FOLDER, LABEL, SUBFOLDER, DocType
from household_vault.people import Household
from household_vault.vaultroot import MAX_NAME_BYTES, VaultPathError, check_component

DEFAULT_NAME = "Document"
MAX_DESCRIPTION = 80

_POLICIES = (
    DocType.life_policy,
    DocType.health_policy,
    DocType.vehicle_policy,
    DocType.home_policy,
    DocType.travel_policy,
    DocType.gadget_policy,
    DocType.accident_policy,
)
_CARD_DOCS = (DocType.card_statement, DocType.card_welcome_letter)

DESCRIPTION: dict[DocType, str] = {
    **dict.fromkeys(_POLICIES, "{label} - {insurer}"),
    DocType.tax_invoice: "Invoice - {seller} - {product}",
    DocType.warranty_card: "Warranty card - {brand} {product}",
    DocType.aadhaar: "{label} - {holder}",
    DocType.pan: "{label} - {holder}",
    DocType.card_front: "Card - {bank} ending {last4}",
    **dict.fromkeys(_CARD_DOCS, "{label} - {bank} ending {last4}"),
    DocType.prescription: "Prescription - {doctor}",
    DocType.lab_report: "Lab report - {lab}",
}
_FALLBACK_FIELDS = (
    "insurer",
    "seller",
    "brand",
    "bank",
    "hospital",
    "lab",
    "issuer",
    "employer",
    "provider",
)
_PLACEHOLDER = re.compile(r"\{(\w+)\}")
# Identifier shapes that must never reach a name, written as the model might have put them
# into a text field: a GSTIN, a PAN, or nine or more digits with single spaces or hyphens.
_IDENTIFIER_SHAPES = (
    re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][A-Z0-9]{3}\b", re.IGNORECASE),
    re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b", re.IGNORECASE),
    re.compile(r"\d(?:[ \-]?\d){8,}"),
)


def scrub_identifiers(text: str) -> str:
    """The text with anything shaped like an identifier left out."""
    for shape in _IDENTIFIER_SHAPES:
        text = shape.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def _text(value: JsonValue | None) -> str:
    """A field value as plain text for a name, without identifiers that were read into a
    text field."""
    return scrub_identifiers(value) if isinstance(value, str) else ""


def _last4(value: object) -> str | None:
    """Exactly four digits, or None: nothing longer ever reaches a description."""
    if not isinstance(value, str):
        return None
    found = re.search(r"(\d{4})\D*$", value)
    return found.group(1) if found else None


def _render(template: str, values: Mapping[str, str]) -> str:
    """Fill the template; a part ("- {seller}") whose fields are all empty is left out."""
    parts: list[str] = []
    for index, segment in enumerate(template.split(" - ")):
        names = [n for n in _PLACEHOLDER.findall(segment) if n != "label"]
        if names and not any(values.get(n) for n in names):
            continue
        text = _PLACEHOLDER.sub(lambda m: values.get(m.group(1), ""), segment)
        text = re.sub(r"\s+", " ", text).strip().removesuffix(" ending").strip()
        if text or index == 0:
            parts.append(text)
    return " - ".join(parts)


def describe(doc_type: DocType, fields: Mapping[str, JsonValue], last4: str | None = None) -> str:
    """The short description in a file name. Never carries an identifier: the only digits that
    come from an identifier are a card's last four."""
    label = LABEL.get(doc_type, DEFAULT_NAME)
    values = {"label": label}
    for name, value in fields.items():
        if name != "last4":
            values[name] = _text(value)
    values["last4"] = (
        _last4(last4) or (_last4(fields.get("last4")) if doc_type in _CARD_DOCS else None) or ""
    )
    template = DESCRIPTION.get(doc_type)
    if template is None:
        extra = next((values[n] for n in _FALLBACK_FIELDS if values.get(n)), "")
        return clean_component(f"{label} - {extra}" if extra else label, MAX_DESCRIPTION)
    return clean_component(_render(template, values), MAX_DESCRIPTION)


def _unsafe(char: str) -> bool:
    if char in "/\\:" or char == "\x00":
        return True
    try:
        check_component("a" + char)
    except VaultPathError:
        return True
    return False


def clean_component(text: str, max_len: int = 80, max_bytes: int | None = None) -> str:
    """Text made safe as one part of a path: NFC, slashes, colons and control characters turned
    into spaces, no leading dots or trailing dots and spaces, cut at a word boundary to at most
    `max_len` characters (and `max_bytes` bytes of UTF-8). Empty becomes "Document"."""
    spaced = "".join(" " if _unsafe(c) else c for c in unicodedata.normalize("NFC", text))
    cleaned = re.sub(r" +", " ", spaced).lstrip(". ").rstrip(". ")
    if not cleaned:
        return DEFAULT_NAME
    budget = MAX_NAME_BYTES if max_bytes is None else min(max_bytes, MAX_NAME_BYTES)
    cut = cleaned[:max_len]
    while len(cut.encode()) > budget and cut:
        cut = cut[:-1]
    if cut != cleaned and cleaned[len(cut) : len(cut) + 1] != " " and " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    cut = cut.rstrip(". ")
    return cut or DEFAULT_NAME


def filed_name(doc_date: date, description: str, ext: str) -> str:
    """`<YYYY-MM-DD> <clean description>.<ext>`, within the vault's name limit."""
    if not re.fullmatch(r"[A-Za-z0-9]{1,8}", ext):
        raise ValueError(f"not a usable extension: {ext!r}")
    prefix, suffix = f"{doc_date.isoformat()} ", f".{ext}"
    room = MAX_NAME_BYTES - len(prefix.encode()) - len(suffix.encode())
    text = clean_component(scrub_identifiers(description), MAX_DESCRIPTION, max_bytes=room)
    return check_component(f"{prefix}{text}{suffix}")


def folder_for(doc_type: DocType, owner: str, household: Household) -> str:
    """`Home` or the person's name, then the area folder, then the subfolder if the type has one."""
    first = (
        "Home"
        if owner == "home"
        else clean_component(household.by_id(owner).name, max_bytes=MAX_NAME_BYTES)
    )
    parts = [first, AREA_FOLDER[AREA[doc_type]]]
    if doc_type in SUBFOLDER:
        parts.append(SUBFOLDER[doc_type])
    return "/".join(parts)
