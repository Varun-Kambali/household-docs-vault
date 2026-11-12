from vault_synth.checks import TEST_CARD_NUMBERS, luhn_valid, verhoeff_valid
from vault_synth.model import SynthDoc

from household_vault.doctypes import DocType


def test_verhoeff_and_luhn_known_values() -> None:
    assert verhoeff_valid("2363")  # standard Verhoeff example
    assert not verhoeff_valid("2364")
    assert luhn_valid("4111111111111111")
    assert not luhn_valid("4111111111111112")


def test_aadhaar_numbers_fail_verhoeff(spike_docs) -> None:  # type: ignore[no-untyped-def]
    for d in spike_docs(DocType.aadhaar):
        digits = d.fields["number"].replace(" ", "")
        assert len(digits) == 12
        assert not verhoeff_valid(digits)


def test_card_numbers_are_test_numbers(spike_docs) -> None:  # type: ignore[no-untyped-def]
    for d in spike_docs(DocType.card_front):
        assert d.fields["number"].replace(" ", "") in TEST_CARD_NUMBERS


def test_pan_numbers_have_the_pan_shape(spike_docs) -> None:  # type: ignore[no-untyped-def]
    import re

    for d in spike_docs(DocType.pan):
        assert re.fullmatch(r"ZZ[A-Z]{3}\d{4}[A-Z]", d.fields["number"])


def test_id_pages_carry_specimen(spike_docs) -> None:  # type: ignore[no-untyped-def]
    for t in (DocType.aadhaar, DocType.pan, DocType.card_front):
        for d in spike_docs(t):
            assert any(line.text.strip().upper() == "SPECIMEN" for line in d.lines)


def test_aadhaar_prints_kannada_lines(spike_docs) -> None:  # type: ignore[no-untyped-def]
    for d in spike_docs(DocType.aadhaar):
        assert any(line.lang == "kn" for line in d.lines)


def test_no_doc_has_empty_fields(spike_docs_all: list[SynthDoc]) -> None:
    for d in spike_docs_all:
        assert all(v.strip() for v in d.fields.values()), d.doc_id
