"""Generate a synthetic document set: clean PDFs, phone-style photos and exact ground truth."""

import argparse
import json
import random
from pathlib import Path
from types import ModuleType

import pypdfium2 as pdfium
from faker import Faker
from PIL import Image

from household_vault.doctypes import DocType
from household_vault.safety import assert_safe_path
from vault_synth.model import SynthDoc
from vault_synth.photo import to_photo
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


def _render(pdf_path: Path) -> Image.Image:
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        image: Image.Image = pdf[0].render(scale=DPI / 72).to_pil().convert("RGB")
        return image
    finally:
        pdf.close()


def generate(set_name: str, per_type: int, seed: int, out: Path) -> list[SynthDoc]:
    if set_name != "spike-v0":
        raise ValueError(f"unknown set {set_name!r}")
    out = assert_safe_path(out)
    out.mkdir(parents=True, exist_ok=True)
    docs: list[SynthDoc] = []
    for doc_type, module in TEMPLATES.items():
        for n in range(1, per_type + 1):
            # a string seed hashes the same way on every run and machine
            rng = random.Random(f"{seed}/{doc_type.value}/{n}")
            fake = Faker("en_IN")
            fake.seed_instance(rng.randrange(2**31))
            base_id = f"{doc_type.value}-{n}"
            pdf_path = assert_safe_path(out / f"{base_id}-clean.pdf")
            width, height = module.PAGE
            sheet = Sheet(pdf_path, width, height)
            truth: Truth = module.draw(sheet, rng, fake)
            sheet.save()

            photo, photo_lines = to_photo(_render(pdf_path), sheet.lines, rng)
            jpg_path = assert_safe_path(out / f"{base_id}-photo.jpg")
            photo.save(jpg_path, format="JPEG", quality=90)

            for variant, fname, lines in (
                ("clean", pdf_path.name, sheet.lines),
                ("photo", jpg_path.name, photo_lines),
            ):
                docs.append(
                    SynthDoc(
                        doc_id=f"{base_id}-{variant}",
                        base_id=base_id,
                        doc_type=doc_type,
                        person=truth.person,
                        variant=variant,
                        files=[fname],
                        fields=dict(truth.fields),
                        printed=dict(truth.printed),
                        lines=lines,
                        field_lines={k: list(v) for k, v in truth.field_lines.items()},
                    )
                )
    for d in docs:
        assert_safe_path(out / f"{d.doc_id}.json").write_text(d.model_dump_json(indent=2) + "\n")
    manifest = {
        "set": set_name,
        "seed": seed,
        "per_type": per_type,
        "documents": [
            {"doc_id": d.doc_id, "doc_type": d.doc_type.value, "files": d.files} for d in docs
        ],
    }
    assert_safe_path(out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return docs


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="vault_synth")
    p.add_argument("--set", dest="set_name", default="spike-v0")
    p.add_argument("--per-type", type=int, default=2)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args(argv)
    docs = generate(a.set_name, a.per_type, a.seed, a.out)
    print(f"wrote {len(docs)} documents to {a.out}")
