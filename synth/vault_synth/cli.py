"""Generate a synthetic document set: clean PDFs, phone photos, scans, locked PDFs and truth.

Each base document draws everything from a seed made of the set seed, the type and its number, so
any subset of types, splits or variants regenerates exactly the same documents.
"""

import argparse
import json
import random
from collections.abc import Collection
from dataclasses import asdict, dataclass, replace
from importlib import metadata
from pathlib import Path
from types import ModuleType
from typing import Literal

from faker import Faker
from PIL import Image
from pydantic import JsonValue

from household_vault.doctypes import AREA, AREA_FOLDER, OWNER, REQUIRED, SUBFOLDER, DocType
from household_vault.reading.lines import Line
from household_vault.reading.render import render_page
from household_vault.reasons import PRIORITY, Reason
from household_vault.safety import assert_safe_path
from household_vault.schemas import SCHEMAS
from vault_synth.household import HOUSEHOLD, CastMember, draw_cast
from vault_synth.model import SynthDoc
from vault_synth.photo import to_photo
from vault_synth.sets import LOCKABLE, SETS, SetSpec, lowest_base, split_of
from vault_synth.sheet import Sheet, Truth
from vault_synth.templates import (
    aadhaar,
    card_front,
    health_policy,
    lab_report,
    pan,
    prescription,
    tax_invoice,
    vehicle_policy,
    warranty_card,
)
from vault_synth.templates._kit import DrawOpts

TEMPLATES: dict[DocType, ModuleType] = {
    DocType.health_policy: health_policy,
    DocType.vehicle_policy: vehicle_policy,
    DocType.warranty_card: warranty_card,
    DocType.tax_invoice: tax_invoice,
    DocType.aadhaar: aadhaar,
    DocType.pan: pan,
    DocType.card_front: card_front,
    DocType.prescription: prescription,
    DocType.lab_report: lab_report,
}
DPI = 200
LIBRARIES = ("faker", "reportlab", "pillow", "pypdfium2")
ALL_SPLITS = ("train", "val", "test")


@dataclass
class _Back:
    sheet: Sheet
    cvv_line: int


@dataclass
class _Base:
    truth: Truth
    sheet: Sheet
    back: _Back | None
    asks: list[str]
    seed: str


def _render(pdf_path: Path) -> Image.Image:
    return render_page(pdf_path.read_bytes(), 0, dpi=DPI)


def _forced(doc_type: DocType, n: int, spec: SetSpec) -> tuple[bool, str | None]:
    """The two guarantees per val and test split: an outsider prescription, a pan with no number.

    Fixed per base number, so a base draws the same whichever subset is generated.
    """
    split = split_of(n)
    if split == "train" or lowest_base(split, spec.per_type_hand) != n:
        return False, None
    if doc_type is DocType.prescription:
        return True, None
    if doc_type is DocType.pan:
        return False, "number"
    return False, None


def _build(
    doc_type: DocType, n: int, spec: SetSpec, path: Path, back_path: Path, password: str | None
) -> _Base:
    module = TEMPLATES[doc_type]
    seed = f"{spec.seed}/{doc_type.value}/{n}"
    rng = random.Random(seed)
    # a string seed hashes the same way on every run and machine
    fake = Faker("en_IN")
    fake.seed_instance(rng.randrange(2**31))
    outsider, forced_drop = _forced(doc_type, n, spec)
    # outsiders and unclear names belong to documents that have an owner, not to home documents
    people_spec = replace(spec, outsider_rate=1.0) if outsider else spec
    if OWNER[doc_type].home:
        people_spec = replace(spec, outsider_rate=0.0, ambiguous_rate=0.0)
    cast, reasons = draw_cast(rng, people_spec, rng.randint(*module.N_PEOPLE))
    roll = rng.random() < spec.missing_required_rate
    # the owner's own field stays on the page, so the app can still tell whose document it is
    candidates = sorted(REQUIRED[doc_type] - set(OWNER[doc_type].owner_fields))
    drop = forced_drop or (rng.choice(candidates) if roll and candidates else None)
    asks = [*reasons, *([Reason.missing_required] if drop else [])]

    sheet = Sheet(path, *module.PAGE, password=password)
    truth: Truth = module.draw(sheet, rng, fake, cast, DrawOpts(spec.absent_rate, drop))
    back: _Back | None = None
    if doc_type is DocType.card_front and n % 2 == 0:
        back_sheet = Sheet(back_path, *module.PAGE)
        cvv, line = module.draw_back(back_sheet, rng)
        back = _Back(back_sheet, line)
        truth.add("cvv", cvv, cvv, [len(sheet.lines) + line])
    sheet.save()
    if back:
        back.sheet.save()
    ordered = sorted(asks, key=PRIORITY.index)
    return _Base(truth, sheet, back, [str(r) for r in ordered], seed)


def _typed(doc_type: DocType, truth: Truth) -> dict[str, JsonValue]:
    """Every schema field, in the schema's own types; None where the page prints nothing."""
    schema = SCHEMAS[doc_type]
    unknown = set(truth.fields) - set(schema.model_fields)
    if unknown:
        raise ValueError(f"{doc_type.value} prints fields its schema lacks: {sorted(unknown)}")
    raw = {name: truth.fields.get(name) for name in schema.model_fields}
    dumped: dict[str, JsonValue] = schema.model_validate(raw).model_dump(mode="json")
    return dumped


def _ownership(doc_type: DocType, truth: Truth) -> tuple[str | None, list[str], str | None]:
    rule = OWNER[doc_type]
    owner: str | None = None
    if rule.home:
        owner = "home"
    else:
        owner = next(
            (p for f in rule.owner_fields for p in truth.people.get(f, []) if p is not None), None
        )
    linked: list[str] = []
    for f in rule.linked_fields:
        for p in truth.people.get(f, []):
            if p is not None and p not in linked:
                linked.append(p)
    folder = None
    if owner is not None:
        who = "Home" if owner == "home" else HOUSEHOLD.by_id(owner).name
        parts = [who, AREA_FOLDER[AREA[doc_type]]]
        if doc_type in SUBFOLDER:
            parts.append(SUBFOLDER[doc_type])
        folder = "/".join(parts)
    return owner, linked, folder


def _scan_pdf(image: Image.Image, path: Path) -> None:
    """The scanner's JPEG wrapped full page in a PDF with no text layer."""
    image.save(path, format="PDF", resolution=float(DPI))


def _treat(
    kind: Literal["photo", "scan"], base: _Base, base_id: str, out: Path
) -> tuple[list[str], list[Line]]:
    """Make the photo or scan files of a base and return their names and all lines."""
    rng = random.Random(f"{base.seed}/{kind}")
    stem = f"{base_id}-{kind}"
    sheets = [(base.sheet, out / f"{base_id}-clean.pdf", "")]
    if base.back:
        sheets.append((base.back.sheet, out / f"{base_id}-clean-back.pdf", "-back"))
    files: list[str] = []
    lines: list[Line] = []
    for page, (sheet, pdf_path, suffix) in enumerate(sheets):
        image, moved = to_photo(_render(pdf_path), sheet.lines, rng, kind)
        if kind == "scan":
            name = f"{stem}{suffix}.pdf"
            _scan_pdf(image, assert_safe_path(out / name))
        else:
            name = f"{stem}{suffix}.jpg"
            image.save(assert_safe_path(out / name), format="JPEG", quality=90)
        files.append(name)
        lines += [ln.model_copy(update={"page": page}) for ln in moved]
    return files, lines


def generate(
    set_name: str,
    out: Path,
    *,
    splits: Collection[str] = ALL_SPLITS,
    types: Collection[DocType] | None = None,
    spec: SetSpec | None = None,
) -> list[SynthDoc]:
    if set_name == "spike-v0":
        raise ValueError("spike-v0 is frozen; check out 5b7c3fd to regenerate it")
    if set_name not in SETS:
        raise ValueError(f"unknown set {set_name!r}")
    spec = spec or SETS[set_name]
    out = assert_safe_path(out)
    out.mkdir(parents=True, exist_ok=True)
    docs: list[SynthDoc] = []
    for doc_type in TEMPLATES:
        if types is not None and doc_type not in types:
            continue
        for n in range(1, spec.per_type_hand + 1):
            if split_of(n) not in splits:
                continue
            docs += _make_base(doc_type, n, spec, out)
    for d in docs:
        # ground truth has no OCR confidence; leaving it out keeps the truth files small
        text = d.model_dump_json(indent=2, exclude={"lines": {"__all__": {"confidence"}}})
        assert_safe_path(out / f"{d.doc_id}.json").write_text(text + "\n")
    assert_safe_path(out / "household.json").write_text(HOUSEHOLD.model_dump_json(indent=2) + "\n")
    manifest = {
        "set": set_name,
        "seed": spec.seed,
        "spec": asdict(spec),
        # Drawing and fake data move with these; the truth files are what stays comparable.
        "libraries": {name: metadata.version(name) for name in LIBRARIES},
        "documents": [
            {
                "doc_id": d.doc_id,
                "doc_type": d.doc_type.value,
                "split": d.split,
                "files": d.files,
            }
            for d in docs
        ],
    }
    assert_safe_path(out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return docs


def _make_base(doc_type: DocType, n: int, spec: SetSpec, out: Path) -> list[SynthDoc]:
    base_id = f"{doc_type.value}-{n}"
    clean = assert_safe_path(out / f"{base_id}-clean.pdf")
    clean_back = assert_safe_path(out / f"{base_id}-clean-back.pdf")
    base = _build(doc_type, n, spec, clean, clean_back, None)
    owner, linked, folder = _ownership(doc_type, base.truth)
    fields = _typed(doc_type, base.truth)
    front = list(base.sheet.lines)
    clean_lines = front + (
        [ln.model_copy(update={"page": 1}) for ln in base.back.sheet.lines] if base.back else []
    )
    clean_files = [clean.name, *([clean_back.name] if base.back else [])]

    Variant = Literal["clean", "photo", "scan", "locked"]

    def doc(
        variant: Variant, files: list[str], lines: list[Line], password: str | None = None
    ) -> SynthDoc:
        return SynthDoc(
            doc_id=f"{base_id}-{variant}",
            base_id=base_id,
            doc_type=doc_type,
            person=base.truth.person,
            variant=variant,
            files=files,
            fields=dict(fields),
            printed=dict(base.truth.printed),
            lines=lines,
            field_lines={k: list(v) for k, v in base.truth.field_lines.items()},
            set_name=spec.name,
            split=split_of(n),
            owner=owner,
            linked_people=list(linked),
            area=AREA[doc_type].value,
            folder=folder,
            expected_ask=list(base.asks),
            password=password,
        )

    made = [doc("clean", clean_files, clean_lines)]
    kinds: list[Literal["photo", "scan"]] = ["photo", "scan"]
    for kind in kinds:
        files, lines = _treat(kind, base, base_id, out)
        made.append(doc(kind, files, lines))
    if doc_type in LOCKABLE:
        password = f"pw-{base_id}"
        locked = assert_safe_path(out / f"{base_id}-locked.pdf")
        # the same page again from the same seed, now behind a password
        again = _build(doc_type, n, spec, locked, out / "unused-back.pdf", password)
        made.append(doc("locked", [locked.name], list(again.sheet.lines), password))
    return made


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="vault_synth")
    p.add_argument("--set", dest="set_name", default="eval-v1")
    p.add_argument("--splits", default=",".join(ALL_SPLITS))
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args(argv)
    docs = generate(a.set_name, a.out, splits=a.splits.split(","))
    print(f"wrote {len(docs)} documents to {a.out}")


__all__ = ["TEMPLATES", "CastMember", "generate", "main"]
