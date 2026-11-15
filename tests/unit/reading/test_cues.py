from household_vault.doctypes import DocType
from household_vault.reading.cues import TYPE_CUES, CueCheck, cue_check
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
        assert cue_check(spec.title, doc_type).verdict == "agrees", doc_type
