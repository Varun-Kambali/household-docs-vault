from datetime import date

from vault_synth.household import HOUSEHOLD

from household_vault.doctypes import DocType
from household_vault.filing.decide import Overrides, decide
from household_vault.reading.cues import CueCheck
from household_vault.reasons import Reason
from tests.conftest import TODAY, reading_of, row


def test_a_purchase_goes_home_linked_to_the_buyer():
    d = decide(reading_of(DocType.tax_invoice, buyer="Ravi K Rao"), HOUSEHOLD, TODAY, [])
    assert (d.outcome, d.owner, d.linked, d.folder) == ("file", "home", ["p1"], "Home/Purchases")
    assert d.area == "purchases"


def test_a_family_floater_sits_with_the_policyholder():
    d = decide(
        reading_of(
            DocType.health_policy,
            policyholder="Kavita Rao",
            insured=["Kavita Rao", "Kiran Rao", "Anita Sharma"],
        ),
        HOUSEHOLD,
        TODAY,
        [],
    )
    assert d.owner == "p2" and d.linked == ["p2", "p3"] and d.folder == "Kavita Rao/Insurance"


def test_a_vehicle_policy_files_under_insurance_and_papers_under_vehicle():
    pol = decide(reading_of(DocType.vehicle_policy, policyholder="Ravi Rao"), HOUSEHOLD, TODAY, [])
    assert pol.folder == "Ravi Kumar Rao/Insurance"
    rc = decide(
        reading_of(DocType.registration_certificate, person_name="Ravi Rao"), HOUSEHOLD, TODAY, []
    )
    assert rc.folder == "Ravi Kumar Rao/Vehicle"


def test_a_missing_required_field_asks_and_an_optional_issue_does_not():
    d = decide(reading_of(DocType.pan, holder="Ravi Rao", number=None), HOUSEHOLD, TODAY, [])
    assert Reason.missing_required in d.reasons
    d = decide(
        reading_of(
            DocType.health_policy, policyholder="Ravi Rao", issues={"premium": "not an amount"}
        ),
        HOUSEHOLD,
        TODAY,
        [],
    )
    assert d.outcome == "file"
    card = reading_of(
        DocType.card_front,
        holder="RAVI K RAO",
        number=None,
        secret_values={"number": "4111111111111111"},
    )
    assert Reason.missing_required not in decide(card, HOUSEHOLD, TODAY, []).reasons


def test_a_required_field_with_an_issue_is_a_field_issue():
    r = reading_of(
        DocType.pan, holder="Ravi Rao", number=None, issues={"number": "not an identifier"}
    )
    d = decide(r, HOUSEHOLD, TODAY, [])
    assert Reason.field_issue in d.reasons and Reason.missing_required not in d.reasons


def test_one_bad_item_of_a_list_names_the_list_field():
    # the second medicine failed to parse: the list is not required, so the prescription files
    r = reading_of(
        DocType.prescription,
        patient="Kavita Rao",
        medicines=[{"name": "Cetirizine"}],
        issues={"medicines[1]": "not an object"},
    )
    assert decide(r, HOUSEHOLD, TODAY, []).outcome == "file"
    # and a required list field that failed item by item is a field issue, not missing
    r = reading_of(
        DocType.marriage_certificate,
        number=None,
        parties=None,
        issues={"number": "x", "parties[0]": "y"},
    )
    d = decide(r, HOUSEHOLD, TODAY, [])
    assert Reason.field_issue in d.reasons and Reason.missing_required not in d.reasons


def test_a_cue_conflict_asks_about_the_type_and_the_date_falls_back():
    d = decide(
        reading_of(
            DocType.aadhaar,
            holder="Ravi Rao",
            type_check=CueCheck("conflicts", DocType.tax_invoice),
        ),
        HOUSEHOLD,
        TODAY,
        [],
    )
    assert Reason.type_unsure in d.reasons and (d.doc_date, d.date_source) == (TODAY, "received")
    assert d.outcome == "ask"


def test_the_document_date_wins_when_the_type_has_one():
    d = decide(
        reading_of(DocType.tax_invoice, buyer="Ravi Rao", invoice_date="2026-03-05"),
        HOUSEHOLD,
        TODAY,
        [],
    )
    assert (d.doc_date, d.date_source) == (date(2026, 3, 5), "document")
    bad = decide(
        reading_of(DocType.tax_invoice, buyer="Ravi Rao", invoice_date="soon"),
        HOUSEHOLD,
        TODAY,
        [],
    )
    assert (bad.doc_date, bad.date_source) == (TODAY, "received")


def test_a_renewal_is_not_a_possible_copy():
    filed = [
        row(
            "d1",
            doc_type=DocType.health_policy,
            fields={"policy_number": "P1", "start_date": "2025-04-01"},
        )
    ]
    renewal = reading_of(
        DocType.health_policy,
        policyholder="Ravi Rao",
        policy_number="P 1",
        start_date="2026-04-01",
        end_date="2027-03-31",
    )
    assert decide(renewal, HOUSEHOLD, TODAY, filed).possible_copy_of is None
    rescan = reading_of(
        DocType.health_policy,
        policyholder="Ravi Rao",
        policy_number="P 1",
        start_date="2025-04-01",
        end_date="2026-03-31",
    )
    d = decide(rescan, HOUSEHOLD, TODAY, filed)
    assert d.possible_copy_of == "d1" and Reason.possible_copy in d.reasons
    kept = decide(rescan, HOUSEHOLD, TODAY, filed, Overrides(keep_copy=True))
    assert kept.possible_copy_of is None and kept.outcome == "file"


def test_a_copy_needs_every_key_value_and_the_same_type():
    filed = [row("d1", doc_type=DocType.pan, fields={"number": "ABCDE1234F"})]
    same = reading_of(DocType.pan, holder="Ravi Rao", number="abcde 1234f")
    assert decide(same, HOUSEHOLD, TODAY, filed).possible_copy_of == "d1"
    other_type = reading_of(DocType.aadhaar, holder="Ravi Rao", number="ABCDE1234F")
    assert decide(other_type, HOUSEHOLD, TODAY, filed).possible_copy_of is None
    unread = reading_of(DocType.pan, holder="Ravi Rao", number=None, issues={"number": "x"})
    blank_filed = [row("d2", doc_type=DocType.pan, fields={"number": None})]
    assert decide(unread, HOUSEHOLD, TODAY, blank_filed).possible_copy_of is None


def test_descriptions_never_carry_an_identifier():
    card = reading_of(
        DocType.card_front,
        holder="RAVI K RAO",
        bank="Nilgiri Bank",
        number=None,
        secret_values={"number": "4111111111111111"},
    )
    d = decide(card, HOUSEHOLD, TODAY, [])
    assert (d.last4, d.description) == ("1111", "Card - Nilgiri Bank ending 1111")
    assert "4111" not in repr(d)


def test_a_card_copy_compares_last4_with_the_filed_cards_field():
    fields = {"bank": "Nilgiri Bank", "expiry": "08/29", "last4": "1111"}
    filed = [row("c1", doc_type=DocType.card_front, fields=fields)]
    card = reading_of(
        DocType.card_front,
        holder="RAVI K RAO",
        bank="Nilgiri Bank",
        expiry="08/29",
        number=None,
        secret_values={"number": "4111111111111111"},
    )
    assert decide(card, HOUSEHOLD, TODAY, filed).possible_copy_of == "c1"
    other = [row("c2", doc_type=DocType.card_front, fields={**fields, "last4": "4444"})]
    assert decide(card, HOUSEHOLD, TODAY, other).possible_copy_of is None


def test_a_card_with_no_number_is_unreadable_not_a_field_to_type():
    card = reading_of(DocType.card_front, holder="RAVI K RAO", number=None)
    d = decide(card, HOUSEHOLD, TODAY, [])
    assert Reason.card_unreadable in d.reasons and Reason.missing_required not in d.reasons


def test_no_english_and_failed_reads():
    nothing = decide(reading_of(None), HOUSEHOLD, TODAY, [])
    assert nothing.reasons == [Reason.no_english]
    assert (nothing.outcome, nothing.folder, nothing.area, nothing.owner) == (
        "ask",
        None,
        None,
        None,
    )
    broken = reading_of(DocType.pan, holder="Ravi Rao", issues={"_json": "no"})
    assert Reason.read_failed in decide(broken, HOUSEHOLD, TODAY, []).reasons


def test_the_other_type_asks_about_the_type():
    d = decide(reading_of(DocType.other), HOUSEHOLD, TODAY, [])
    assert d.reasons == [Reason.type_unsure] and d.folder is None


def test_unknown_unsure_and_missing_names():
    unknown = decide(reading_of(DocType.pan, holder="Anita Sharma"), HOUSEHOLD, TODAY, [])
    assert unknown.reasons == [Reason.person_unknown] and unknown.owner is None
    assert unknown.printed_names == {"holder": "Anita Sharma"}
    unsure = decide(reading_of(DocType.pan, holder="K Rao"), HOUSEHOLD, TODAY, [])
    assert unsure.reasons == [Reason.person_unsure] and unsure.printed_names == {"holder": "K Rao"}
    none = decide(reading_of(DocType.prescription, patient=None), HOUSEHOLD, TODAY, [])
    assert Reason.person_unknown in none.reasons


def test_a_list_owner_field_gives_its_first_household_name():
    r = reading_of(DocType.marriage_certificate, parties=["Anita Sharma", "Kavita Rao", "Ravi Rao"])
    d = decide(r, HOUSEHOLD, TODAY, [])
    assert d.owner == "p2" and d.linked == ["p1", "p2"]


def test_overrides_replace_type_owner_and_fields_before_the_rules_run():
    r = reading_of(None)
    d = decide(
        r,
        HOUSEHOLD,
        TODAY,
        [],
        Overrides(
            doc_type=DocType.pan,
            owner="p3",
            fields={"holder": "Anita Sharma", "number": "ABCDE1234F"},
        ),
    )
    assert d.outcome == "file" and d.owner == "p3" and d.folder == "Kiran Rao/Identity"
    assert d.linked == ["p3"]
    fixed = reading_of(DocType.pan, holder="Ravi Rao", number=None, issues={"number": "x"})
    d = decide(fixed, HOUSEHOLD, TODAY, [], Overrides(fields={"number": "ABCDE1234F"}))
    assert d.outcome == "file"
    conflict = reading_of(
        DocType.aadhaar, holder="Ravi Rao", type_check=CueCheck("conflicts", DocType.pan)
    )
    d = decide(conflict, HOUSEHOLD, TODAY, [], Overrides(doc_type=DocType.aadhaar))
    assert Reason.type_unsure not in d.reasons


def test_the_home_owner_override_files_to_home():
    r = reading_of(DocType.pan, holder="Anita Sharma")
    d = decide(r, HOUSEHOLD, TODAY, [], Overrides(owner="home"))
    assert d.owner == "home" and d.folder == "Home/Identity"


def test_reasons_come_in_priority_order_without_repeats():
    r = reading_of(DocType.pan, holder="Anita Sharma", number=None)
    reasons = decide(r, HOUSEHOLD, TODAY, []).reasons
    assert reasons == [Reason.person_unknown, Reason.missing_required]
