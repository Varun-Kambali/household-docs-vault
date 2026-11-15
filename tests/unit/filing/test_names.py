from datetime import date

import pytest
from vault_synth.household import HOUSEHOLD

from household_vault.doctypes import DocType
from household_vault.filing.names import (
    DESCRIPTION,
    clean_component,
    describe,
    filed_name,
    folder_for,
)
from household_vault.vaultroot import MAX_NAME_BYTES, check_component


def test_descriptions_never_carry_an_identifier():
    assert "4321" not in describe(
        DocType.aadhaar, {"holder": "Ravi Rao", "number": "SPECIMEN 4321"}
    )
    card = describe(DocType.card_front, {"bank": "Nilgiri Bank"}, last4="1111")
    assert card == "Card - Nilgiri Bank ending 1111"


def test_a_long_digit_run_in_a_text_field_is_dropped():
    text = describe(DocType.tax_invoice, {"seller": "Shop", "product": "Fridge 123456789012"})
    assert "123456789" not in text


def test_each_type_gets_its_format():
    assert describe(DocType.health_policy, {"insurer": "Nilgiri Life"}) == (
        "Health policy - Nilgiri Life"
    )
    assert describe(DocType.tax_invoice, {"seller": "Shop", "product": "Mixer"}) == (
        "Invoice - Shop - Mixer"
    )
    assert describe(DocType.warranty_card, {"brand": "Aqua", "product": "Purifier"}) == (
        "Warranty card - Aqua Purifier"
    )
    assert describe(DocType.pan, {"holder": "Ravi Rao"}) == "PAN card - Ravi Rao"
    assert describe(DocType.prescription, {"doctor": "Dr A Nair"}) == "Prescription - Dr A Nair"
    assert describe(DocType.lab_report, {"lab": "City Labs"}) == "Lab report - City Labs"


def test_other_types_use_the_first_name_like_field_that_is_set():
    assert describe(DocType.payslip, {"employer": "Acme"}) == "Payslip - Acme"
    assert describe(DocType.certificate, {"issuer": "Uni"}) == "Certificate - Uni"
    assert describe(DocType.khata, {}) == "Khata"


def test_a_missing_part_is_left_out_not_printed_blank():
    assert describe(DocType.health_policy, {}) == "Health policy"
    assert describe(DocType.tax_invoice, {"seller": "Shop"}) == "Invoice - Shop"
    assert describe(DocType.card_front, {"bank": "Nilgiri Bank"}) == "Card - Nilgiri Bank"


def test_card_documents_use_their_stored_last_four():
    assert describe(DocType.card_statement, {"bank": "Nilgiri Bank", "last4": "1111"}) == (
        "Card statement - Nilgiri Bank ending 1111"
    )
    # only four digits ever get in
    assert "9999" not in describe(DocType.card_front, {"bank": "B"}, last4="99991111")


def test_every_description_format_names_known_types():
    assert set(DESCRIPTION) <= set(DocType)


def test_clean_component_cannot_escape(vault):  # Review Focus 10
    for text in ("../../etc", "a/b\\c", "..", "\x00x", ".hidden", "name. ", "x" * 300, ""):
        name = clean_component(text)
        assert "/" not in name and not name.startswith(".") and name not in ("", "..")
        assert len(name) <= 80
        vault.path(f"Home/{name}")


def test_clean_component_details():
    assert clean_component("a:b/c") == "a b c"
    assert clean_component("  two   spaces ") == "two spaces"
    assert clean_component("") == "Document"
    assert clean_component("‮txt.exe") == "txt.exe"  # bidi override
    assert clean_component("one two three four", max_len=10) == "one two"
    assert clean_component("é") == "é"  # NFC


def test_clean_component_respects_a_byte_budget():
    kannada = "ರವಿ " * 60
    name = clean_component(kannada, max_len=80, max_bytes=100)
    assert len(name.encode()) <= 100 and name


def test_filed_name_fits_the_vault_limit():
    for desc in ("Health policy - Nilgiri Life", "ರವಿ" * 200, "../x", ""):
        name = filed_name(date(2026, 4, 1), desc, "pdf")
        check_component(name)
        assert name.startswith("2026-04-01 ") and name.endswith(".pdf")
        assert len(name.encode()) <= MAX_NAME_BYTES
    assert filed_name(date(2026, 4, 1), "Invoice - Shop", "pdf") == "2026-04-01 Invoice - Shop.pdf"


def test_filed_name_refuses_an_odd_extension():
    with pytest.raises(ValueError):
        filed_name(date(2026, 4, 1), "x", "p/df")


def test_folder_for():
    assert folder_for(DocType.tax_invoice, "home", HOUSEHOLD) == "Home/Purchases"
    assert folder_for(DocType.health_policy, "p2", HOUSEHOLD) == "Kavita Rao/Insurance"
    assert folder_for(DocType.vehicle_policy, "p1", HOUSEHOLD) == "Ravi Kumar Rao/Insurance"
    assert folder_for(DocType.registration_certificate, "p1", HOUSEHOLD) == (
        "Ravi Kumar Rao/Vehicle"
    )
    assert folder_for(DocType.prescription, "p3", HOUSEHOLD) == "Kiran Rao/Medical/Reports"
