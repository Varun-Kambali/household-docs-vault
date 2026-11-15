"""The data-driven form layouts: every readable type has one, and they keep the privacy rules."""

import random
import re
from pathlib import Path

import pytest
from faker import Faker
from vault_synth.cli import TEMPLATES, generate
from vault_synth.forms import FORM_SPECS, safe_digits
from vault_synth.household import CastMember
from vault_synth.model import SynthDoc

from household_vault.checks import TEST_CARD_NUMBERS, luhn_valid, verhoeff_valid
from household_vault.doctypes import AREA, OWNER, REQUIRED, Area, DocType
from household_vault.schemas import SCHEMAS
from tests.conftest import group_by_base
from tests.unit.test_leak_scan import scan_text


@pytest.fixture(scope="module")
def form_docs(tmp_path_factory: pytest.TempPathFactory) -> list[SynthDoc]:
    out = tmp_path_factory.mktemp("forms")
    return generate("eval-v1", out, splits=("test",), types=set(FORM_SPECS))


def test_every_readable_type_has_a_template() -> None:
    assert set(TEMPLATES) == set(DocType) - {DocType.other, DocType.visit_recording}


def test_form_fields_are_schema_fields() -> None:
    for t, spec in FORM_SPECS.items():
        assert {f.name for f in spec.fields} <= set(SCHEMAS[t].model_fields), t


def test_a_form_prints_every_required_field_and_its_owner_field() -> None:
    for t, spec in FORM_SPECS.items():
        names = {f.name for f in spec.fields}
        assert REQUIRED[t] <= names, t
        assert set(OWNER[t].owner_fields) <= names, t


def test_forms_cover_the_forty_one_other_types() -> None:
    assert len(FORM_SPECS) == 41
    assert set(FORM_SPECS) == set(TEMPLATES) - {t for t in TEMPLATES if t.value in HAND_DRAWN}


HAND_DRAWN = {
    "health_policy",
    "vehicle_policy",
    "warranty_card",
    "tax_invoice",
    "aadhaar",
    "pan",
    "card_front",
    "prescription",
    "lab_report",
}


def test_form_ids_use_the_reserved_prefix_and_carry_specimen(form_docs: list[SynthDoc]) -> None:
    checked = 0
    for d in form_docs:
        if AREA[d.doc_type] is Area.identity:
            number = d.fields["number"]
            if number is not None:
                assert str(number).startswith("ZZ"), d.doc_id
                checked += 1
            assert any(ln.text.strip() == "SPECIMEN" for ln in d.lines), d.doc_id
    assert checked


def test_no_generated_line_holds_a_real_shaped_number(form_docs: list[SynthDoc]) -> None:
    assert not [h for d in form_docs for ln in d.lines for h in scan_text(ln.text)]


def test_card_forms_print_only_the_last_four_of_a_test_number(form_docs: list[SynthDoc]) -> None:
    ends = {n[-4:] for n in TEST_CARD_NUMBERS}
    seen = [
        d
        for d in form_docs
        if d.doc_type in (DocType.card_statement, DocType.card_welcome_letter)
        and d.fields["last4"] is not None
    ]
    assert seen
    for d in seen:
        assert d.fields["last4"] in ends
        assert d.printed["last4"] == f"XXXX XXXX XXXX {d.fields['last4']}"


def test_form_truth_is_typed_complete_and_matches_the_page(form_docs: list[SynthDoc]) -> None:
    for d in form_docs:
        schema = SCHEMAS[d.doc_type]
        assert set(d.fields) == set(schema.model_fields), d.doc_id
        assert schema.model_validate(d.fields).model_dump(mode="json") == d.fields, d.doc_id
        present = {k for k, v in d.fields.items() if v is not None}
        assert set(d.printed) == set(d.field_lines) == present, d.doc_id
        texts = [ln.text for ln in d.lines]
        for name, idx in d.field_lines.items():
            assert all(0 <= i < len(texts) for i in idx), (d.doc_id, name)


def test_form_owner_and_folder_follow_the_rules(form_docs: list[SynthDoc]) -> None:
    for d in form_docs:
        if OWNER[d.doc_type].home:
            assert d.owner == "home" and d.folder and d.folder.startswith("Home/"), d.doc_id
        elif d.owner is not None:
            assert d.area and d.folder and f"/{d.area.title()}" in d.folder, d.doc_id


def test_every_form_type_has_all_its_variants(form_docs: list[SynthDoc]) -> None:
    from vault_synth.sets import LOCKABLE

    bases = group_by_base(form_docs)
    assert len(bases) == 41
    for base in bases.values():
        variants = {d.variant for d in base}
        assert {"clean", "photo", "scan"} <= variants
        assert ("locked" in variants) == (base[0].doc_type in LOCKABLE)


def test_scan_photo_form_draws_an_image_area(tmp_path: Path) -> None:
    assert FORM_SPECS[DocType.scan_photo].image_box
    assert not FORM_SPECS[DocType.scan_report].image_box


def test_safe_digits_fail_the_checksums() -> None:
    rng = random.Random(3)
    for _ in range(300):
        assert not verhoeff_valid(safe_digits(rng, 12))
        assert not luhn_valid(safe_digits(rng, 16))
        assert not luhn_valid(safe_digits(rng, 13))
    assert len(safe_digits(rng, 10)) == 10


def test_form_makers_return_a_value_and_its_printed_text() -> None:
    rng, fake = random.Random(1), Faker("en_IN")
    cast = [CastMember("p1", "Ravi Kumar Rao"), CastMember("p2", "Kavita Rao")]
    for t, spec in FORM_SPECS.items():
        for f in spec.fields:
            value, printed = f.make(rng, fake, cast)
            assert isinstance(printed, str) and printed, (t, f.name)
            assert value is not None, (t, f.name)
            assert not re.search(r"[—]", printed)


ORG_PRIORITY = ("insurer", "bank", "employer", "hospital", "issuer", "brand", "seller", "provider")


def test_the_band_names_the_documents_own_organisation(form_docs: list[SynthDoc]) -> None:
    named = 0
    for d in form_docs:
        if d.variant != "clean":
            continue
        spec = FORM_SPECS[d.doc_type]
        # the band's heading is the one line printed in the top 4% of the page
        band = next((ln.text for ln in d.lines if ln.bbox[1] < 0.04), None)
        org = next((n for n in ORG_PRIORITY if n in {f.name for f in spec.fields}), None)
        if org is None:
            assert band in spec.issuers, d.doc_id
        elif org in d.printed:
            assert band == d.printed[org], (d.doc_id, band, d.printed[org])
            named += 1
        else:
            assert band is None, (d.doc_id, band)
    assert named >= 20


def test_card_digits_match_the_network(form_docs: list[SynthDoc]) -> None:
    from vault_synth.templates.card_front import _network

    by_network: dict[str, set[str]] = {}
    for n in TEST_CARD_NUMBERS:
        by_network.setdefault(_network(n), set()).add(n[-4:])
    seen = 0
    for d in form_docs:
        tail, network = d.fields.get("last4"), d.fields.get("network")
        if tail is not None and network is not None:
            seen += 1
            assert tail in by_network[str(network)], (d.doc_id, network, tail)
    assert seen


def test_an_absent_organisation_is_named_nowhere_on_the_page() -> None:
    """If the truth says bank (or insurer, hospital...) is None, no organisation name of that
    type is printed, in the lines or in the PDF's text layer."""
    import pypdfium2 as pdfium
    from vault_synth.sets import load_set

    from tests.conftest import EVAL_V1

    docs = load_set(EVAL_V1)
    checked = 0
    for t, spec in FORM_SPECS.items():
        org = next((n for n in ORG_PRIORITY if n in {f.name for f in spec.fields}), None)
        mine = [d for d in docs if d.doc_type is t]
        if org is None:
            continue
        # every value the set uses for this field, and the type's fallback issuer names
        names = {str(d.fields[org]) for d in mine if d.fields.get(org) is not None}
        names |= set(spec.issuers)
        for d in mine:
            if d.fields.get(org) is not None:
                continue
            checked += 1
            blob = "\n".join(ln.text for ln in d.lines)
            if d.variant == "clean":
                pdf = pdfium.PdfDocument(str(EVAL_V1 / d.files[0]))
                blob += "\n" + pdf[0].get_textpage().get_text_range()
                pdf.close()
            assert not [n for n in names if n in blob], d.doc_id
    assert checked
