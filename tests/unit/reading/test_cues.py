import pytest

from household_vault.doctypes import DocType
from household_vault.reading.cues import GENERIC_CUES, TYPE_CUES, CueCheck, cue_check
from household_vault.schemas import SCHEMAS


def test_a_cue_conflict_is_reported():
    assert cue_check("TAX INVOICE  GSTIN 29ABCDE", DocType.aadhaar) == CueCheck(
        "conflicts", DocType.tax_invoice
    )


def test_agrees_and_silent():
    assert cue_check("Health Insurance - Policy Schedule", DocType.health_policy).verdict == (
        "agrees"
    )
    assert cue_check("some unrelated words", DocType.pan) == CueCheck("silent", None)


def test_every_type_has_cues_and_they_are_lowercase():
    assert {t for t in SCHEMAS if t is not DocType.other} <= set(TYPE_CUES)
    assert all(c == c.lower() and c for cues in TYPE_CUES.values() for c in cues)


def test_every_form_title_agrees_with_its_own_type():
    import sys

    sys.path.insert(0, "synth")
    from vault_synth.forms import FORM_SPECS

    for doc_type, spec in FORM_SPECS.items():
        verdict = cue_check(spec.title, doc_type).verdict
        # a generic title ("Service Report") is never proof, so it stays silent
        expected = "silent" if spec.title.lower() in GENERIC_CUES else "agrees"
        assert verdict == expected, doc_type


@pytest.mark.parametrize(
    "claimed",
    [
        DocType.health_policy,
        DocType.travel_policy,
        DocType.home_policy,
        DocType.life_policy,
        DocType.accident_policy,
    ],
)
def test_a_motor_policy_is_not_another_policy(claimed):
    assert cue_check("Motor Insurance Policy Schedule", claimed) == CueCheck(
        "conflicts", DocType.vehicle_policy
    )


def test_a_marriage_certificate_is_not_a_registration_certificate():
    text = "Certificate of Registration of Marriage"
    assert cue_check(text, DocType.registration_certificate) == CueCheck(
        "conflicts", DocType.marriage_certificate
    )
    assert cue_check(text, DocType.marriage_certificate).verdict == "agrees"


@pytest.mark.parametrize(
    ("text", "claimed", "expected"),
    [
        # the claimed cue (13 characters) is longer than the other type's (11)
        ("Tax invoice - warranty card", DocType.warranty_card, CueCheck("agrees")),
        # the other type's cue is the longer one
        (
            "Vehicle Service Invoice tax invoice",
            DocType.tax_invoice,
            CueCheck("conflicts", DocType.vehicle_service_record),
        ),
        (
            "Salary slip income tax department",
            DocType.payslip,
            CueCheck("conflicts", DocType.pan),
        ),
    ],
)
def test_the_longest_cue_wins(text, claimed, expected):
    assert cue_check(text, claimed) == expected


@pytest.mark.parametrize(
    "phrase", ["policy schedule", "reference range", "final bill", "service report"]
)
def test_a_generic_phrase_alone_is_silent(phrase):
    for doc_type in (DocType.health_policy, DocType.lab_report, DocType.hospital_bill):
        assert cue_check(phrase.upper(), doc_type) == CueCheck("silent")
