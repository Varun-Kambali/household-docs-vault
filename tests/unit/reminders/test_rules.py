from datetime import date

from household_vault.doctypes import DocType
from household_vault.reminders.rules import RULES, Days, Months, fire_date, lead_key
from household_vault.search.vocab import DATE_ROLES


def by_name():
    return {r.name: r for r in RULES}


def test_the_rules_are_design_5_6():
    rules = by_name()
    assert list(rules) == [
        "policy_renewal",
        "premium_due",
        "warranty_end",
        "period_end",
        "passport_expiry",
        "licence_rc_puc",
        "rent_end",
        "card_expiry",
        "card_payment_due",
        "next_checkup",
    ]
    assert rules["policy_renewal"].leads == (Days(60), Days(30), Days(7))
    assert rules["passport_expiry"].leads == (Months(9),)
    assert (
        rules["card_payment_due"].leads == (Days(5), Days(1))
        and not rules["card_payment_due"].calendar
    )
    assert rules["next_checkup"].leads == (Days(3), Days(1))
    assert [r.name for r in RULES if not r.calendar] == [
        "premium_due",
        "card_payment_due",
        "next_checkup",
    ]


def test_a_rule_only_names_dates_its_types_have():
    for rule in RULES:
        assert rule.types
        for t in rule.types:
            if rule.date in ("warranty_parts", "card_expiry"):
                continue
            assert rule.date in DATE_ROLES[t], (rule.name, t)


def test_the_checkup_rule_covers_the_medical_types_with_a_due_role():
    types = by_name()["next_checkup"].types
    assert DocType.lab_report not in types
    assert types == {
        DocType.prescription,
        DocType.scan_photo,
        DocType.scan_report,
        DocType.discharge_summary,
        DocType.hospital_bill,
    }
    assert len(by_name()["policy_renewal"].types) == 7


def test_lead_keys_and_fire_dates():
    assert lead_key(Days(60)) == "d60" and lead_key(Months(9)) == "m9"
    assert fire_date(date(2027, 3, 14), Days(60)) == date(2027, 1, 13)
    assert fire_date(date(2027, 5, 31), Months(9)) == date(2026, 8, 31)
    assert fire_date(date(2027, 11, 30), Months(9)) == date(2027, 2, 28)
    assert fire_date(date(2028, 11, 29), Months(9)) == date(2028, 2, 29)
