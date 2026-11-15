"""The eval-v1 data model: a small household, typed truth, absent fields, scans and locked PDFs."""

import json
import random
from dataclasses import replace
from pathlib import Path

import pypdfium2 as pdfium
import pytest
from vault_synth.cli import generate
from vault_synth.household import AMBIGUOUS, HOUSEHOLD, draw_cast
from vault_synth.model import SynthDoc
from vault_synth.sets import SETS, locked_password, split_of

from household_vault.doctypes import DocType
from household_vault.reading.render import LockedPdfError, page_count
from household_vault.reasons import Reason
from household_vault.schemas import SCHEMAS
from tests.conftest import group_by_base


def test_a_subset_regenerates_identically(tmp_path: Path, eval_docs: list[SynthDoc]) -> None:
    alone = generate("eval-v1", tmp_path, splits=("test",), types=[DocType.aadhaar])
    together = [d for d in eval_docs if d.doc_type is DocType.aadhaar]
    assert alone
    assert [d.model_dump() for d in alone] == [d.model_dump() for d in together]


def test_each_split_has_an_outsider_and_a_missing_required_field(tmp_path: Path) -> None:
    docs = generate(
        "eval-v1", tmp_path, splits=("val", "test"), types=[DocType.prescription, DocType.pan]
    )
    for split in ("val", "test"):
        asks = {r for d in docs if d.split == split for r in d.expected_ask}
        assert {"person_unknown", "missing_required"} <= asks, split


def test_truth_is_typed_and_complete(eval_docs: list[SynthDoc]) -> None:
    for d in eval_docs:
        schema = SCHEMAS[d.doc_type]
        assert set(d.fields) == set(schema.model_fields)
        assert schema.model_validate(d.fields).model_dump(mode="json") == d.fields


def test_absent_fields_are_null_and_not_on_the_page(eval_docs: list[SynthDoc]) -> None:
    nulls = [(d, k) for d in eval_docs for k, v in d.fields.items() if v is None]
    assert nulls
    assert all(k not in d.printed and k not in d.field_lines for d, k in nulls)
    for d in eval_docs:
        present = {k for k, v in d.fields.items() if v is not None}
        assert set(d.printed) == set(d.field_lines) == present, d.doc_id


def test_owner_folder_and_links_follow_the_rules(eval_docs: list[SynthDoc]) -> None:
    for d in eval_docs:
        if d.doc_type is DocType.tax_invoice:
            assert (d.owner, d.folder) == ("home", "Home/Purchases")
        if d.doc_type is DocType.prescription and d.owner:
            assert d.folder == f"{HOUSEHOLD.by_id(d.owner).name}/Medical/Reports"
        if d.doc_type is DocType.health_policy and d.owner:
            assert d.owner in d.linked_people


def test_outsiders_and_shared_initials_expect_a_question(tmp_path: Path) -> None:
    always = replace(SETS["eval-v1"], outsider_rate=1.0, missing_required_rate=0.0)
    docs = generate(
        "eval-v1", tmp_path, splits=("test",), types=[DocType.prescription], spec=always
    )
    assert docs
    assert all(d.owner is None and d.expected_ask == ["person_unknown"] for d in docs)
    spec = replace(SETS["eval-v1"], outsider_rate=0.0, ambiguous_rate=1.0)
    cast, asks = draw_cast(random.Random(1), spec, 1)
    assert cast[0].printed == AMBIGUOUS and asks == [Reason.person_unsure]


def test_scan_and_locked_variants(eval_docs: list[SynthDoc], eval_dir: Path) -> None:
    scan = next(x for x in eval_docs if x.variant == "scan")
    pdf = pdfium.PdfDocument(str(eval_dir / scan.files[0]))
    assert pdf[0].get_textpage().get_text_range() == ""
    pdf.close()
    locked = next(x for x in eval_docs if x.variant == "locked")
    data = (eval_dir / locked.files[0]).read_bytes()
    with pytest.raises(LockedPdfError):
        page_count(data)
    assert page_count(data, password=locked_password(locked.base_id)) == 1


def test_variants_share_truth_and_split(eval_docs: list[SynthDoc]) -> None:
    for docs in group_by_base(eval_docs).values():
        assert len({json.dumps(d.fields, sort_keys=True) for d in docs}) == 1
        assert len({d.split for d in docs}) == 1


def test_card_back_carries_the_cvv_and_specimen(eval_docs: list[SynthDoc]) -> None:
    d = next(x for x in eval_docs if x.doc_type is DocType.card_front and len(x.files) == 2)
    assert d.fields["cvv"]
    assert any(ln.page == 1 and ln.text.strip() == "SPECIMEN" for ln in d.lines)


def test_splits_and_the_frozen_spike_set(tmp_path: Path) -> None:
    assert [split_of(n) for n in (1, 2, 5, 6, 10)] == ["val", "train", "test", "val", "test"]
    with pytest.raises(ValueError, match="frozen"):
        generate("spike-v0", tmp_path)


def test_eval_documents_keep_the_privacy_rules(eval_docs: list[SynthDoc]) -> None:
    import re

    from household_vault.checks import TEST_CARD_NUMBERS, gstin_valid, verhoeff_valid

    for d in eval_docs:
        number = d.fields.get("number")
        if d.doc_type is DocType.aadhaar and number:
            assert not verhoeff_valid(str(number).replace(" ", "")), d.doc_id
        if d.doc_type is DocType.card_front and number:
            assert number in TEST_CARD_NUMBERS, d.doc_id
        if d.doc_type is DocType.pan and number:
            assert re.fullmatch(r"ZZ[A-Z]{3}\d{4}[A-Z]", str(number)), d.doc_id
        gstin = d.fields.get("gstin")
        if gstin:
            assert not gstin_valid(str(gstin)), d.doc_id
        if d.doc_type in (DocType.aadhaar, DocType.pan, DocType.card_front):
            assert any("SPECIMEN" in ln.text for ln in d.lines), d.doc_id


def test_every_split_member_variant_and_the_guarantees_hold_per_base(tmp_path: Path) -> None:
    docs = generate("eval-v1", tmp_path, splits=("val", "test"), types=[DocType.prescription])
    by_split = {
        s: [d for d in docs if d.split == s and d.variant == "clean"] for s in ("val", "test")
    }
    # the lowest base of each split is the outsider one, whatever the random rates did
    assert by_split["val"][0].base_id == "prescription-1" and by_split["val"][0].owner is None
    assert by_split["test"][0].base_id == "prescription-5" and by_split["test"][0].owner is None


def test_the_lowest_pan_base_of_each_split_prints_no_number(tmp_path: Path) -> None:
    docs = generate("eval-v1", tmp_path, splits=("val", "test"), types=[DocType.pan])
    for split, base in (("val", 1), ("test", 5)):
        pan = next(d for d in docs if d.doc_id == f"pan-{base}-clean")
        assert pan.split == split
        assert pan.fields["number"] is None
        assert "number" not in pan.printed
        assert "missing_required" in pan.expected_ask
