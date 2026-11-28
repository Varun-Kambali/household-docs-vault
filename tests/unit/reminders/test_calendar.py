import re
from datetime import date
from urllib.parse import parse_qs, urlsplit

from household_vault.db import DocumentRow
from household_vault.doctypes import DocType
from household_vault.reminders.calendar import calendar_link, title_of
from household_vault.reminders.compute import ReminderSettings, reminders
from household_vault.reminders.rules import RULES_BY_NAME
from tests.conftest import add_doc


def doc_of(store, doc_id) -> DocumentRow:
    return store.document(doc_id)


def test_calendar_titles_never_carry_numbers(store):
    add_doc(
        store, "r", "registration_certificate",
        {"registration_no": "KA01AB1234", "expiry_date": "2027-03-14"}, ["x"],
    )  # fmt: skip
    add_doc(store, "w", "extended_warranty",
            {"seller": "Croma 24x7 Store 1234", "end_date": "2027-03-14"}, ["x"])  # fmt: skip
    for doc_id, rule in (("r", "licence_rc_puc"), ("w", "period_end")):
        title = title_of(RULES_BY_NAME[rule], doc_of(store, doc_id), None)
        assert not re.search(r"\d{4}", title)
        assert "KA01" not in title and "AB1234" not in title
    assert title_of(RULES_BY_NAME["period_end"], doc_of(store, "w"), None) == (
        "Cover ends for extended warranty, Croma 24x7 Store"
    )


def test_a_title_has_the_verb_label_part_and_place(store):
    add_doc(store, "v", "vehicle_policy", {"insurer": "Tata AIG", "end_date": "2027-03-14"}, ["x"])
    add_doc(store, "p", "passport", {"expiry_date": "2027-03-14"}, ["x"])
    add_doc(store, "w", "warranty_card",
            {"seller": "LG", "purchase_date": "2024-03-14"}, ["x"])  # fmt: skip
    assert title_of(RULES_BY_NAME["policy_renewal"], doc_of(store, "v"), None) == (
        "Renew vehicle insurance policy, Tata AIG"
    )
    assert title_of(RULES_BY_NAME["passport_expiry"], doc_of(store, "p"), None) == "Renew passport"
    assert title_of(RULES_BY_NAME["warranty_end"], doc_of(store, "w"), "compressor") == (
        "Warranty ends for warranty card, compressor, LG"
    )


def test_a_title_is_clipped_to_60_characters_on_a_word_boundary(store):
    add_doc(store, "v", "vehicle_policy",
            {"insurer": "The Oriental Insurance Company of Greater Bengaluru"}, ["x"])  # fmt: skip
    title = title_of(RULES_BY_NAME["policy_renewal"], doc_of(store, "v"), None)
    assert len(title) <= 60 and not title.endswith((" ", ","))
    assert title == "Renew vehicle insurance policy, The Oriental Insurance"[: len(title)]


def test_the_link_is_an_all_day_event_on_the_due_date(store):
    add_doc(store, "v", "vehicle_policy", {"insurer": "Tata AIG", "end_date": "2027-03-14"}, ["x"])
    (rem,) = [
        r for r in reminders(store, date(2027, 3, 9), ReminderSettings())
        if r.rule == "policy_renewal"
    ]  # fmt: skip
    url = calendar_link(rem)
    assert url is not None
    parts = urlsplit(url)
    assert (parts.scheme, parts.netloc, parts.path) == (
        "https", "calendar.google.com", "/calendar/render",
    )  # fmt: skip
    q = parse_qs(parts.query)
    assert sorted(q) == ["action", "dates", "text"]
    assert q["action"] == ["TEMPLATE"] and q["dates"] == ["20270314/20270315"]
    assert q["text"] == [rem.title]


def test_the_day_after_rolls_over_a_month_end(store):
    add_doc(store, "p", "passport", {"expiry_date": "2027-03-31"}, ["x"])
    (rem,) = reminders(store, date(2026, 12, 1), ReminderSettings())
    assert "dates=20270331%2F20270401" in (calendar_link(rem) or "")


def test_a_due_without_a_calendar_rule_has_no_link(store):
    add_doc(store, "c", "card_statement", {"bank": "HDFC", "payment_due_date": "2027-03-14"}, ["x"])
    found = [r for r in reminders(store, date(2027, 3, 12), ReminderSettings())
             if r.rule == "card_payment_due"]  # fmt: skip
    assert found and calendar_link(found[0]) is None
    assert DocType.card_statement in RULES_BY_NAME["card_payment_due"].types
