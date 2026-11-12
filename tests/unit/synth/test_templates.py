import collections
import json
import re
from pathlib import Path

from vault_synth.cli import generate
from vault_synth.model import SynthDoc

from household_vault.doctypes import DocType


def norm(s: str) -> str:
    return re.sub(r"[\W_]+", "", s.lower())


def test_every_field_is_supported_by_a_line(spike_docs_all: list[SynthDoc]) -> None:
    for d in spike_docs_all:
        assert set(d.field_lines) == set(d.fields) == set(d.printed)
        for name, idx in d.field_lines.items():
            supporting = " ".join(d.lines[i].text for i in idx)
            assert idx and norm(d.printed[name]) in norm(supporting), (d.doc_id, name)


def test_set_has_both_variants_of_each_document(spike_docs_all: list[SynthDoc]) -> None:
    assert len(spike_docs_all) == 36
    by_base = collections.Counter(d.base_id for d in spike_docs_all)
    assert set(by_base.values()) == {2}
    for d in spike_docs_all:
        assert d.doc_id == f"{d.base_id}-{d.variant}"


def test_field_keys_match_the_brief(spike_docs_all: list[SynthDoc]) -> None:
    expected = {
        DocType.health_policy: "insurer policy_number policyholder insured nominee sum_insured "
        "premium start_date end_date claim_helpline",
        DocType.vehicle_policy: "insurer policy_number policyholder registration_number idv "
        "ncb_percent premium start_date end_date claim_helpline",
        DocType.warranty_card: "brand product model serial_number purchase_date seller "
        "seller_location warranty_parts",
        DocType.tax_invoice: "seller seller_location gstin invoice_number invoice_date product "
        "model serial_number amount",
        DocType.aadhaar: "holder number date_of_birth address",
        DocType.pan: "holder number date_of_birth father_name",
        DocType.card_front: "bank network holder number expiry",
        DocType.prescription: "patient doctor hospital date medicines next_visit",
        DocType.lab_report: "patient lab date tests",
    }
    for d in spike_docs_all:
        assert set(d.fields) == set(expected[d.doc_type].split()), d.doc_id


def test_clean_and_photo_share_truth(spike_docs_all: list[SynthDoc]) -> None:
    by_base: dict[str, list[SynthDoc]] = collections.defaultdict(list)
    for d in spike_docs_all:
        by_base[d.base_id].append(d)
    for pair in by_base.values():
        a, b = pair
        assert a.fields == b.fields and a.printed == b.printed
        assert [x.text for x in a.lines] == [x.text for x in b.lines]


def test_dates_and_amounts_are_normalised(spike_docs_all: list[SynthDoc]) -> None:
    for d in spike_docs_all:
        for k, v in d.fields.items():
            if k.endswith("_date") or k in {"date", "next_visit", "date_of_birth"}:
                assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", v), (d.doc_id, k, v)
            if k in {"sum_insured", "premium", "idv", "amount"}:
                assert v.isdigit(), (d.doc_id, k, v)


def test_boxes_are_normalised(spike_docs_all: list[SynthDoc]) -> None:
    for d in spike_docs_all:
        for line in d.lines:
            x0, y0, x1, y1 = line.bbox
            assert 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1, (d.doc_id, line)


def test_invoice_state_and_financial_year_are_consistent(spike_docs) -> None:  # type: ignore[no-untyped-def]
    codes = {
        "Karnataka": "29",
        "Tamil Nadu": "33",
        "Telangana": "36",
        "Maharashtra": "27",
        "Kerala": "32",
    }
    for d in spike_docs(DocType.tax_invoice):
        text = "\n".join(line.text for line in d.lines)
        state = next(s for s in codes if f"Place of supply: {s} ({codes[s]})" in text)
        assert f", {state} - " in text
        assert d.fields["gstin"].startswith(codes[state])
        year, month = int(d.fields["invoice_date"][:4]), int(d.fields["invoice_date"][5:7])
        start = year if month >= 4 else year - 1
        assert f"/{start % 100:02d}-{(start + 1) % 100:02d}/" in d.fields["invoice_number"]


def test_ordinals() -> None:
    from vault_synth.data import ordinal

    got = [ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 18, 21)]
    assert got == ["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "18th", "21st"]


def test_generation_is_deterministic(tmp_path: Path) -> None:
    a = generate("spike-v0", per_type=1, seed=7, out=tmp_path / "a")
    b = generate("spike-v0", per_type=1, seed=7, out=tmp_path / "b")
    assert [d.model_dump() for d in a] == [d.model_dump() for d in b]


def test_generate_writes_files_and_manifest(tmp_path: Path) -> None:
    docs = generate("spike-v0", per_type=1, seed=3, out=tmp_path / "o")
    out = tmp_path / "o"
    manifest = json.loads((out / "manifest.json").read_text())
    assert len(manifest["documents"]) == len(docs) == 18
    for d in docs:
        assert (out / f"{d.doc_id}.json").exists()
        for f in d.files:
            assert (out / f).stat().st_size > 1000
        assert d.files[0].endswith(".pdf" if d.variant == "clean" else ".jpg")
