import json

import pytest

from household_vault.doctypes import DocType
from household_vault.intake.sniff import FileKind
from household_vault.reading.engines import Engines, VisionPageReader
from household_vault.reading.pipeline import read_document
from household_vault.reading.snap import snap_fields, snap_value
from household_vault.reading.source import DocumentSource
from household_vault.schemas import SCHEMAS
from tests.fakes import FakeModels, FakeOcr

LINES = [
    "Name: SURESH N RAO",
    "Western Ghats Life Assurance Limited",
    "Multispeciality Hospital",
    "Dr Bakshi Bakhshi Clinic",
]


@pytest.mark.parametrize(
    ("value", "want"),
    [
        ("SURESHER N RAO", "SURESH N RAO"),
        ("SURESHE N RAO", "SURESH N RAO"),
        ("SURES N RAO", "SURESH N RAO"),
        ("Western Ghat Life Assurance Limited", "Western Ghats Life Assurance Limited"),
        ("Multispecialty Hospital", "Multispeciality Hospital"),
    ],
)
def test_a_slip_snaps_to_the_printed_text(value, want):
    assert snap_value(value, LINES) == want


def test_a_value_on_the_page_is_left_alone():
    assert snap_value("suresh  n rao", LINES) == "suresh  n rao"
    assert snap_value("Western Ghats Life Assurance Limited", LINES) == (
        "Western Ghats Life Assurance Limited"
    )


def test_a_value_that_is_not_on_the_page_stays():
    assert snap_value("Priya Menon", LINES) == "Priya Menon"
    assert snap_value("Priya Menon", []) == "Priya Menon"


def test_a_tie_between_two_different_texts_leaves_the_value():
    lines = ["RAMESH KUMAR", "RAMESH KUMAS"]
    assert snap_value("RAMESH KUMAT", lines) == "RAMESH KUMAT"


def test_snapping_is_deterministic():
    runs = {snap_value("SURESHER N RAO", LINES) for _ in range(5)}
    assert runs == {"SURESH N RAO"}


def test_only_text_kinds_snap_and_lists_snap_item_by_item():
    schema = SCHEMAS[DocType.health_policy]
    lines = ["Name SURESH N RAO", "Policy HP/2024/55123", "Insured SURESH N RAO", "ANITA RAO"]
    fields = {
        "policyholder": "SURESHE N RAO",
        "insured": ["SURES N RAO", "ANITA RAO", "Zed Zed"],
        "policy_number": "HP/2024/55124",
        "sum_insured": "500000",
        "start_date": "2024-01-01",
    }
    out = snap_fields(schema, dict(fields), lines)
    assert out["policyholder"] == "SURESH N RAO"
    assert out["insured"] == ["SURESH N RAO", "ANITA RAO", "Zed Zed"]
    for name in ("policy_number", "sum_insured", "start_date"):
        assert out[name] == fields[name]


def test_dates_amounts_and_identifiers_never_snap():
    schema = SCHEMAS[DocType.health_policy]
    out = snap_fields(
        schema,
        {"policy_number": "HP/2024/5512", "premium": "12,000", "end_date": "31/12/2025"},
        ["HP/2024/55123", "12,000.00", "31/12/2026"],
    )
    assert out == {
        "policy_number": "HP/2024/5512",
        "premium": "12,000",
        "end_date": "31/12/2025",
    }


def _read(photo, fill, ocr_text, doc_type="card_front"):
    engines = Engines(
        VisionPageReader(FakeOcr(text=ocr_text)), FakeModels(type_=doc_type, fill=fill)
    )
    return read_document(DocumentSource(FileKind.jpeg, data=photo), "s", engines, mode="dev")


def test_read_document_snaps_a_name_and_keeps_secrets_out(photo):
    fill = json.dumps({"holder": "SURESHER N RAO", "number": "4111111111111111"})
    r = _read(photo, fill, "SURESH N RAO")
    assert r.fields["holder"] == "SURESH N RAO"
    assert r.fields["number"] is None and r.secret_values["number"] == "4111111111111111"


def test_a_card_page_is_still_scrubbed_after_a_snap(photo):
    fill = json.dumps(
        {
            "holder": "SURESHER N RAO",
            "card_name": "4111 1111 1111 1111",
            "number": "4111111111111111",
        }
    )
    r = _read(photo, fill, "SURESH N RAO")
    assert r.fields["holder"] == "SURESH N RAO"
    assert "4111111111111111" not in json.dumps(r.fields)
    assert "4111 1111 1111 1111" not in json.dumps(r.fields)
