"""The one prompt every candidate gets, and the schema it is shown."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from spikes.reading.engines import OcrLine

PROMPT_VERSION = "v1"

SYSTEM = (
    "You read Indian household documents and return their fields as JSON. "
    "Fill only what is printed on the page. If a field is not printed, use null. "
    "Never guess or invent a value. Write dates as YYYY-MM-DD. "
    "Write amounts and percentages as plain numbers, with no currency symbol or commas. "
    "Copy names, numbers and codes exactly as printed."
)


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


def ocr_to_text(lines: list[OcrLine]) -> str:
    """Join OCR lines top to bottom; lines on the same row are joined left to right."""
    ordered = sorted(lines, key=lambda ln: ((ln.bbox[1] + ln.bbox[3]) / 2, ln.bbox[0]))
    rows: list[list[OcrLine]] = []
    for ln in ordered:
        mid = (ln.bbox[1] + ln.bbox[3]) / 2
        if rows:
            last = rows[-1][-1]
            if abs(mid - (last.bbox[1] + last.bbox[3]) / 2) < (last.bbox[3] - last.bbox[1]) / 2:
                rows[-1].append(ln)
                continue
        rows.append([ln])
    return "\n".join("  ".join(x.text for x in sorted(r, key=lambda x: x.bbox[0])) for r in rows)
