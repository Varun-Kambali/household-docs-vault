"""Copy the smoke documents' recordings out of a val run, masking number-shaped misreads.

    uv run python -m evals.import_smoke --source var/recordings/val-v4 --dest <folder>

The source is a folder of recordings written by a run on `val` (git-ignored). Each smoke id from
smoke.json is found by the `doc_id` inside the recordings, exactly once, and written to dest
under its own key. Every text a recording holds is scanned with `scan_text`'s finder, test cards
allowed, and each hit has every digit but the last four replaced with X, separators kept. The
recording's own `prompt_version` and engine are kept as recorded. A summary of how many values
were masked, by field, is printed; never the values.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from evals.recordings import load_smoke
from household_vault.checks import find_numbers
from household_vault.leakscan import scan_text
from household_vault.reading.recorded import Recording, write_recording

ROOT = Path(__file__).resolve().parents[1]
EVAL_V1 = ROOT / "evals" / "datasets" / "eval-v1"
DEST = ROOT / "evals" / "recordings" / "eval-v1" / "smoke"
_NOT_TEXT = frozenset({"sha256", "doc_id", "engine", "prompt_version"})


class SmokeImportError(Exception):
    """The source does not hold every smoke document exactly once."""


def mask_text(text: str) -> tuple[str, int]:
    """The text with every digit but the last four of each card- or Aadhaar-shaped number as
    X (published test cards left alone), and how many numbers that was."""
    spans: list[list[int]] = []
    for hit in find_numbers(text, allow_test_cards=True):
        if spans and hit.start < spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], hit.end)
        else:
            spans.append([hit.start, hit.end])
    chars = list(text)
    for start, end in spans:
        digits = [i for i in range(start, end) if chars[i].isdigit()]
        for i in digits[:-4]:
            chars[i] = "X"
    return "".join(chars), len(spans)


def _walk(node: Any, field: str, counts: Counter[str]) -> Any:
    if isinstance(node, str):
        masked, n = mask_text(node)
        if n:
            counts[field] += n
        return masked
    if isinstance(node, list):
        return [_walk(x, field, counts) for x in node]
    if isinstance(node, dict):
        return {
            k: v if k in _NOT_TEXT else _walk(v, f"{field}.{k}" if field else k, counts)
            for k, v in node.items()
        }
    return node


def mask_recording(body: dict[str, Any]) -> tuple[dict[str, Any], Counter[str]]:
    """The recording's JSON with every text masked, and the count of masked numbers by field."""
    counts: Counter[str] = Counter()
    return _walk(body, "", counts), counts


def import_smoke(source: Path, dest: Path, ids: list[str]) -> Counter[str]:
    """Write the masked recordings of ids from source into dest; return masked counts by field."""
    found: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(source.glob("*.json")):
        body = json.loads(path.read_text(encoding="utf-8"))
        if body.get("doc_id") in ids:
            found.setdefault(body["doc_id"], []).append(body)
    problems = [i for i in ids if len(found.get(i, [])) != 1]
    if problems:
        raise SmokeImportError(f"not found exactly once in the source: {problems}")
    total: Counter[str] = Counter()
    for doc_id in ids:
        masked, counts = mask_recording(found[doc_id][0])
        total.update(counts)
        rec = Recording.model_validate(masked)
        write_recording(dest, rec)
        if scan_text(rec.model_dump_json(by_alias=True), allow_test_cards=True):
            raise SmokeImportError(f"a number-shaped value is left in {doc_id}")
    return total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals.import_smoke")
    parser.add_argument("--source", required=True)
    parser.add_argument("--dest", default=str(DEST))
    args = parser.parse_args(argv)
    ids = load_smoke(EVAL_V1)
    dest = Path(args.dest)
    old = sorted(dest.glob("*.json")) if dest.is_dir() else []
    try:
        counts = import_smoke(Path(args.source), dest, ids)
    except SmokeImportError as err:
        print(err)
        return 1
    new = {p.name for p in dest.glob("*.json")}
    print(f"wrote {len(ids)} recordings to {dest}")
    print(f"replaced files: {sum(1 for p in old if p.name in new)} of {len(old)} old")
    print(f"old files with no new one: {sorted(p.name for p in old if p.name not in new)}")
    print(f"new keys not among the old files: {sorted(new - {p.name for p in old})}")
    print(f"masked numbers: {sum(counts.values())} by field {dict(counts)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
