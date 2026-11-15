"""The extraction prompts and the schema they are shown.

PROMPT_V1 is frozen: the spike results record prompt_version v1 and the fine-tune path was
proven on it. A new prompt is a new constant beside it, never an edit of this text.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from household_vault.doctypes import LABEL, DocType
from household_vault.reading.lines import Line


@dataclass(frozen=True)
class Prompt:
    version: str
    system: str


PROMPT_V1 = Prompt(
    "v1",
    (
        "You read Indian household documents and return their fields as JSON. "
        "Fill only what is printed on the page. If a field is not printed, use null. "
        "Never guess or invent a value. A field whose description says YYYY-MM-DD is a date: "
        "write it that way. Write every other field exactly as printed. "
        "Write amounts and percentages as plain numbers, with no currency symbol or commas."
    ),
)

# The app's prompt: v1 plus two rules from the M1 error review. v1 stays as it was.
PROMPT_V2 = Prompt(
    "v2",
    PROMPT_V1.system
    + " Write medicine names without the form word printed before them (Tab, Cap, Syp, Inj)."
    + " Give a list field one item per printed entry.",
)

CLASSIFY_SYSTEM = (
    "You sort Indian household documents by type. Read the page text and answer with the one "
    "type that fits best, or other if none fits."
)

# How much page text the type call is shown.
OCR_TEXT_LIMIT = 6000


def _flatten(node: Any, defs: dict[str, Any]) -> Any:
    """Inline $refs and turn pydantic's anyOf-with-null into a nullable type."""
    if isinstance(node, list):
        return [_flatten(n, defs) for n in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        return _flatten(defs[node["$ref"].rsplit("/", 1)[-1]], defs)
    if "anyOf" in node:
        options = [o for o in node["anyOf"] if o.get("type") != "null"]
        merged = _flatten(options[0], defs) if options else {}
        merged = {**merged, **{k: v for k, v in node.items() if k not in ("anyOf", "default")}}
        if len(options) != len(node["anyOf"]) and isinstance(merged.get("type"), str):
            merged["type"] = [merged["type"], "null"]
        return merged
    flat = {k: _flatten(v, defs) for k, v in node.items() if k not in ("$defs", "default")}
    if isinstance(flat.get("properties"), dict):
        flat["properties"] = {
            n: {k: v for k, v in p.items() if k != "title"} for n, p in flat["properties"].items()
        }
        flat["required"] = list(flat["properties"])
        flat["additionalProperties"] = False
    flat.pop("title", None)
    return flat


def schema_for_prompt(schema: type[BaseModel]) -> dict[str, Any]:
    """JSON Schema a small model and Ollama's grammar can follow: no $ref, dates and amounts
    as strings or numbers with a hint, every field listed as required but nullable."""
    raw = schema.model_json_schema()
    flat = _flatten(raw, raw.get("$defs", {}))
    for name, prop in flat["properties"].items():
        if prop.get("format") == "date":
            prop.pop("format")
            prop["description"] = "YYYY-MM-DD"
        # Decimal comes out as number-or-string with a pattern; ask for a plain number
        if "anyOf" in prop or (
            prop.get("type") in (["string", "null"], "string") and "pattern" in prop
        ):
            prop.pop("anyOf", None)
            prop.pop("pattern", None)
            prop["type"] = ["number", "null"]
        flat["properties"][name] = prop
    flat["required"] = list(flat["properties"])
    flat["additionalProperties"] = False
    return flat  # type: ignore[no-any-return]


def schema_json(schema: type[BaseModel]) -> str:
    return json.dumps(schema_for_prompt(schema), ensure_ascii=False)


def user_prompt(doc_type: str, schema_text: str, ocr_text: str | None) -> str:
    parts = [
        f"Document type: {doc_type}.",
        f"Return one JSON object that follows this JSON Schema:\n{schema_text}",
    ]
    if ocr_text is not None:
        parts.append(f"The text read from the page, top to bottom:\n{ocr_text}")
    else:
        parts.append("The page is in the attached image.")
    return "\n\n".join(parts)


def ocr_to_text(lines: Sequence[Line]) -> str:
    """Join OCR lines top to bottom; lines on the same row are joined left to right."""
    ordered = sorted(lines, key=lambda ln: ((ln.bbox[1] + ln.bbox[3]) / 2, ln.bbox[0]))
    rows: list[list[Line]] = []
    for ln in ordered:
        mid = (ln.bbox[1] + ln.bbox[3]) / 2
        if rows:
            last = rows[-1][-1]
            if abs(mid - (last.bbox[1] + last.bbox[3]) / 2) < (last.bbox[3] - last.bbox[1]) / 2:
                rows[-1].append(ln)
                continue
        rows.append([ln])
    return "\n".join("  ".join(x.text for x in sorted(r, key=lambda x: x.bbox[0])) for r in rows)


def classify_schema() -> dict[str, Any]:
    """One required property, `doc_type`, one of every type the reader can name."""
    values = [t.value for t in DocType if t is not DocType.visit_recording]
    return {
        "type": "object",
        "properties": {"doc_type": {"type": "string", "enum": values}},
        "required": ["doc_type"],
        "additionalProperties": False,
    }


def classify_prompt(ocr_text: str) -> str:
    types = "\n".join(
        f"- {t.value}: {LABEL.get(t, 'Other')}" for t in DocType if t is not DocType.visit_recording
    )
    return (
        f"Document types:\n{types}\n\n"
        f"The text read from the page, top to bottom:\n{ocr_text[:OCR_TEXT_LIMIT]}"
    )
