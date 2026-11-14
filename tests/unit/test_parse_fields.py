from datetime import date, timedelta

from household_vault.checks import find_numbers
from household_vault.schemas import (
    Aadhaar,
    CardFront,
    HealthPolicy,
    LabReport,
    Prescription,
    TaxInvoice,
    VehiclePolicy,
)
from household_vault.schemas._coerce import field_kind, secret_fields
from household_vault.schemas.parse import mask_card_numbers, parse_fields, parse_json_fields
from tests.conftest import one_digit_changed, valid_aadhaar, valid_gstin


def test_one_bad_field_does_not_sink_the_document():
    p = parse_fields(
        HealthPolicy, {"policy_number": "P1", "end_date": "next spring", "x": 1}, mode="dev"
    )
    assert p.model.policy_number == "P1" and p.model.end_date is None
    assert set(p.issues) == {"end_date"} and "next spring" not in p.issues["end_date"]


def test_good_fields_are_typed():
    p = parse_fields(
        HealthPolicy,
        {
            "end_date": "18.01.2027",
            "sum_insured": "5 Lakhs",
            "insured": ["A", "B"],
            "nominee": None,
        },
        mode="dev",
    )
    assert p.issues == {}
    assert p.model.end_date == date(2027, 1, 18)
    assert p.model.insured == ["A", "B"]


def test_an_end_before_the_start_is_an_issue():
    p = parse_fields(
        HealthPolicy, {"start_date": "01/04/2026", "end_date": "31/03/2025"}, mode="dev"
    )
    assert p.model.end_date is None and p.issues == {"end_date": "ends before it starts"}
    assert p.model.start_date == date(2026, 4, 1)


def test_a_birth_date_in_the_future_is_an_issue():
    future = (date.today() + timedelta(days=30)).strftime("%d/%m/%Y")
    p = parse_fields(Aadhaar, {"date_of_birth": future}, mode="dev")
    assert p.model.date_of_birth is None and p.issues == {"date_of_birth": "in the future"}


def test_broken_json_gives_empty_fields_and_an_issue():
    p = parse_json_fields(HealthPolicy, "{not json", mode="dev")
    assert p.model == HealthPolicy() and "_json" in p.issues


def test_json_that_is_not_an_object_gives_an_issue():
    assert "_json" in parse_json_fields(HealthPolicy, "[1, 2]", mode="dev").issues
    assert "_json" in parse_fields(HealthPolicy, "text", mode="dev").issues


def test_json_text_parses_field_by_field():
    p = parse_json_fields(VehiclePolicy, '{"ncb_percent": "20%", "idv": "oops"}', mode="dev")
    assert p.model.ncb_percent == 20 and set(p.issues) == {"idv"}


def test_card_number_is_secret_and_must_pass_luhn():
    assert secret_fields(CardFront) == {"number", "cvv"}
    ok = parse_fields(CardFront, {"number": "4111 1111 1111 1111"}, mode="dev")
    assert ok.model.number == "4111111111111111"
    bad = parse_fields(CardFront, {"number": "4111 1111 1111 1112"}, mode="dev")
    assert "number" in bad.issues and "1112" not in bad.issues["number"]


def test_cvv_is_three_or_four_digits():
    assert parse_fields(CardFront, {"cvv": "123"}, mode="dev").model.cvv == "123"
    assert "cvv" in parse_fields(CardFront, {"cvv": "12"}, mode="dev").issues
    assert "cvv" in parse_fields(CardFront, {"cvv": "12345"}, mode="dev").issues


def test_card_numbers_are_masked_in_text():
    assert mask_card_numbers("no 4111 1111 1111 1111 exp") == "no XXXX XXXX XXXX 1111 exp"
    assert mask_card_numbers("policy 1234567890123") == "policy 1234567890123"  # fails Luhn
    assert mask_card_numbers("4111 1111 1111 1112", any_long_run=True) == "XXXX XXXX XXXX 1112"


def test_masking_overlapping_windows_leaves_only_the_last_four():
    masked = mask_card_numbers("4111 1111 1111 1112 12", any_long_run=True)
    assert masked.count("X") >= 12 and "1111" not in masked.replace("1112", "")
    assert find_numbers(masked, allow_test_cards=False, any_long_run=True) == []


def test_parse_fields_flags_a_misread_id_in_app_mode_only():
    misread = one_digit_changed(valid_aadhaar())
    assert parse_fields(Aadhaar, {"number": misread}, mode="app").issues == {
        "number": "number may be misread"
    }
    assert parse_fields(Aadhaar, {"number": misread}, mode="app").model.number is None
    assert parse_fields(Aadhaar, {"number": misread}, mode="dev").issues == {}
    bad_gstin = one_digit_changed(valid_gstin())
    assert "gstin" in parse_fields(TaxInvoice, {"gstin": bad_gstin}, mode="app").issues
    good = parse_fields(TaxInvoice, {"gstin": valid_gstin()}, mode="app")
    assert good.issues == {} and good.model.gstin is not None


def test_field_kinds():
    assert field_kind(HealthPolicy, "policy_number") == "identifier"
    assert field_kind(HealthPolicy, "policyholder") == "name"
    assert field_kind(HealthPolicy, "insured") == "list"
    assert field_kind(HealthPolicy, "end_date") == "date"
    assert field_kind(HealthPolicy, "premium") == "amount"
    assert field_kind(HealthPolicy, "insurer") == "text"
    assert field_kind(Aadhaar, "number") == "aadhaar"
    assert field_kind(Aadhaar, "address") == "address"
    assert field_kind(TaxInvoice, "gstin") == "gstin"
    assert field_kind(Prescription, "medicines") == "list"
    assert field_kind(LabReport, "tests") == "list"
