"""Which synthetic sets the generator builds, how each is split, and how a committed one loads."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from household_vault.doctypes import AREA, Area, DocType
from vault_synth.model import SynthDoc

Split = Literal["train", "val", "test"]


@dataclass(frozen=True)
class SetSpec:
    name: str
    seed: int
    per_type_hand: int  # bases per hand-drawn type
    per_type_form: int  # bases per form-driven type
    absent_rate: float  # an optional row is left off the page
    missing_required_rate: float  # one required field is left off the page
    outsider_rate: float  # the first person printed is nobody in the household
    ambiguous_rate: float  # the first person is printed as initials that fit two people


# search-x1 and search-x2 add documents to the search eval's vault. They follow eval-v1's counts
# and clean variant, and ask nothing: no outsider, no unclear name, no missing required field, so
# every one of their documents files.
SETS: dict[str, SetSpec] = {
    "eval-v1": SetSpec("eval-v1", 7, 10, 5, 0.15, 0.03, 0.05, 0.03),
    "search-x1": SetSpec("search-x1", 11, 10, 5, 0.15, 0.0, 0.0, 0.0),
    "search-x2": SetSpec("search-x2", 12, 10, 5, 0.15, 0.0, 0.0, 0.0),
}

# Types that also arrive locked: the insurance area plus card statements.
LOCKABLE: frozenset[DocType] = frozenset(
    {t for t, a in AREA.items() if a is Area.insurance} | {DocType.card_statement}
)


def split_of(n: int) -> Split:
    """The split of base number n. Whole bases go to one split, so no variant leaks across."""
    if n % 5 == 0:
        return "test"
    if n % 5 == 1:
        return "val"
    return "train"


def base_prefix(spec: SetSpec) -> str:
    """What starts a base id. eval-v1 keeps the bare `<type>-<n>`; every other set names itself,
    so documents of two sets never share an id."""
    return "" if spec.name == "eval-v1" else f"{spec.name}-"


def locked_password(base_id: str) -> str:
    """The password of a base's locked PDF. Derived, never stored in the truth files."""
    return f"pw-{base_id}"


def lowest_base(split: str, count: int) -> int | None:
    """The lowest base number in the split among 1..count (None when the split is empty)."""
    return next((n for n in range(1, count + 1) if split_of(n) == split), None)


def load_set(folder: Path) -> list[SynthDoc]:
    """Read a committed set's truth files, in the order its manifest lists them."""
    manifest = json.loads((folder / "manifest.json").read_text())
    return [
        SynthDoc.model_validate_json((folder / f"{row['doc_id']}.json").read_text())
        for row in manifest["documents"]
    ]
