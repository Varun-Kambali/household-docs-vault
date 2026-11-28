import json
from datetime import date

from household_vault.doctypes import DocType
from household_vault.reminders.compute import ReminderSettings, load_settings, reminders
from household_vault.reminders.rules import RULES, Days, Months
from tests.conftest import add_doc


def fires(found, rule=None):
    return [(r.fire, r.due) for r in found if rule is None or r.rule == rule]


def test_a_policy_ending_on_14_mar_2027_fires_60_30_and_7_days_before(store):
    add_doc(store, "d1", "health_policy", {"insurer": "Star", "end_date": "2027-03-14"}, ["x"])
    found = reminders(store, date(2027, 3, 1), ReminderSettings())
    renewals = [r for r in found if r.rule == "policy_renewal"]
    assert [r.fire for r in renewals] == [date(2027, 1, 13), date(2027, 2, 12), date(2027, 3, 7)]
    assert {r.due for r in renewals} == {date(2027, 3, 14)}
    first = renewals[0]
    assert first.key == "d1:policy_renewal::2027-03-14:d60"
    assert first.person_ids == ("p1",) and first.calendar and not first.custom
    assert first.part is None and first.document_id == "d1"
    assert "health policy" in first.title.lower()


def test_month_leads_clamp_to_the_month_end(store):
    add_doc(store, "a", "passport", {"expiry_date": "2027-05-31"}, ["x"])
    add_doc(store, "b", "passport", {"expiry_date": "2027-11-30"}, ["x"])
    found = reminders(store, date(2026, 8, 1), ReminderSettings())
    assert [(r.document_id, r.fire) for r in found] == [("a", date(2026, 8, 31))]
    assert found[0].key == "a:passport_expiry::2027-05-31:m9"
    later = reminders(store, date(2027, 2, 1), ReminderSettings())
    assert (date(2027, 2, 28), date(2027, 11, 30)) in fires(later)


def test_each_warranty_part_reminds_on_its_own_end(store):
    fields = {
        "purchase_date": "2024-03-14",
        "warranty_parts": [
            {"part": "Compressor", "years": 10},
            {"part": "Comprehensive", "years": 1},
        ],
    }
    add_doc(store, "w", "warranty_card", fields, ["x"])
    found = reminders(store, date(2025, 3, 1), ReminderSettings())
    assert [(r.part, r.due, r.fire) for r in found] == [
        ("Comprehensive", date(2025, 3, 13), date(2025, 2, 11))
    ]
    assert found[0].key == "w:warranty_end:Comprehensive:2025-03-13:d30"
    wide = reminders(store, date(2034, 2, 1), ReminderSettings())
    assert [(r.part, r.due) for r in wide] == [("Compressor", date(2034, 3, 13))]


def test_a_card_expiry_of_06_31_reminds_on_1_jun_2031(store):
    add_doc(store, "c", "card_front", {"bank": "HDFC", "expiry": "06/31"}, ["x"])
    found = reminders(store, date(2031, 5, 1), ReminderSettings())
    assert [(r.rule, r.due, r.fire) for r in found] == [
        ("card_expiry", date(2031, 6, 30), date(2031, 5, 31))
    ]
    assert fires(reminders(store, date(2031, 5, 31), ReminderSettings()))


def test_unreadable_dates_make_no_reminder(store):
    for i, bad in enumerate(["6/31x", "", None, "June"]):
        add_doc(store, f"c{i}", "card_front", {"expiry": bad}, ["x"])
    add_doc(store, "p", "health_policy", {"insurer": "Star"}, ["x"])
    add_doc(store, "q", "health_policy", {"end_date": "not a date"}, ["x"])
    add_doc(store, "w", "warranty_card", {"warranty_parts": [{"part": "A", "years": 1}]}, ["x"])
    add_doc(
        store,
        "w2",
        "warranty_card",
        {"purchase_date": "2024-01-01", "warranty_parts": [{"part": "A", "years": "x"}, 5, {}]},
        ["x"],
    )
    assert reminders(store, date(2027, 1, 1), ReminderSettings(horizon_days=4000)) == []


def test_reminders_follow_the_filed_documents(store):
    add_doc(store, "old", "vehicle_policy", {"end_date": "2027-03-14"}, ["x"])
    today = date(2027, 3, 1)
    assert {r.document_id for r in reminders(store, today, ReminderSettings())} == {"old"}
    store.remove_document("old")
    assert reminders(store, today, ReminderSettings()) == []
    add_doc(store, "new", "vehicle_policy", {"end_date": "2028-03-14"}, ["x"])
    add_doc(store, "old", "vehicle_policy", {"end_date": "2027-03-14"}, ["x"])
    keys = {r.key for r in reminders(store, today, ReminderSettings())}
    assert keys == {f"old:policy_renewal::2027-03-14:d{n}" for n in (60, 30, 7)}
    later = reminders(store, date(2028, 3, 1), ReminderSettings())
    assert {r.document_id for r in later if r.due > date(2028, 1, 1)} == {"new"}


def test_changed_leads_from_settings_replace_the_defaults(store):
    add_doc(store, "d1", "health_policy", {"end_date": "2027-03-14"}, ["x"])
    store.set_setting("reminder_leads", json.dumps({"policy_renewal": ["14d", "2m"]}))
    settings = load_settings(store)
    assert settings.leads["policy_renewal"] == (Days(14), Months(2))
    found = reminders(store, date(2027, 3, 1), settings)
    assert [r.fire for r in found if r.rule == "policy_renewal"] == [
        date(2027, 1, 14),
        date(2027, 2, 28),
    ]
    assert settings.leads_for("passport_expiry") == (Months(9),)


def test_bad_lead_settings_keep_the_defaults(store):
    for raw in ["{", "[]", json.dumps({"policy_renewal": ["x"], "nope": ["3d"]}), "null"]:
        store.set_setting("reminder_leads", raw)
        assert load_settings(store).leads_for("policy_renewal") == (Days(60), Days(30), Days(7))


def test_the_window_runs_from_30_days_past_to_the_horizon(store):
    add_doc(store, "d1", "health_policy", {"end_date": "2027-03-14"}, ["x"])
    pol = lambda today, **kw: [  # noqa: E731
        r for r in reminders(store, today, ReminderSettings(**kw)) if r.rule == "policy_renewal"
    ]
    assert pol(date(2027, 4, 13))  # 30 days past
    assert not pol(date(2027, 4, 14))  # 31 days past
    assert not pol(date(2026, 11, 13))  # first fire 13 Jan is 61 days ahead
    assert pol(date(2026, 11, 14))
    assert len(pol(date(2026, 11, 1), horizon_days=100)) >= 1


def test_done_and_snoozed_reminders_drop_out_until_their_date(store):
    add_doc(store, "d1", "health_policy", {"end_date": "2027-03-14"}, ["x"])
    today = date(2027, 3, 1)
    key60, key30 = "d1:policy_renewal::2027-03-14:d60", "d1:policy_renewal::2027-03-14:d30"
    store.set_reminder_state(key60, "done", None)
    store.set_reminder_state(key30, "snoozed", date(2027, 3, 5))
    keys = {r.key for r in reminders(store, today, ReminderSettings())}
    assert key60 not in keys and key30 not in keys
    keys = {r.key for r in reminders(store, date(2027, 3, 5), ReminderSettings())}
    assert key30 in keys and key60 not in keys


def test_a_renewal_with_a_new_end_date_is_not_marked_done(store):
    add_doc(store, "d1", "health_policy", {"end_date": "2027-03-14"}, ["x"])
    store.set_reminder_state("d1:policy_renewal::2027-03-14:d60", "done", None)
    store.remove_document("d1")
    add_doc(store, "d1", "health_policy", {"end_date": "2028-03-14"}, ["x"])
    found = reminders(store, date(2028, 3, 1), ReminderSettings())
    assert {r.due for r in found} == {date(2028, 3, 14)} and len(found) >= 3


def test_custom_reminders_are_included(store):
    add_doc(store, "d1", "tax_invoice", {"seller": "Croma"}, ["x"])
    cid = store.add_custom_reminder("d1", date(2027, 3, 14), "Check the bill")
    found = reminders(store, date(2027, 3, 1), ReminderSettings())
    assert len(found) == 1
    r = found[0]
    assert r.custom and r.rule == "custom" and r.title == "Check the bill"
    assert r.fire == r.due == date(2027, 3, 14) and not r.calendar
    assert r.key == f"d1:custom::2027-03-14:c{cid}"
    store.set_reminder_state(r.key, "done", None)
    assert reminders(store, date(2027, 3, 1), ReminderSettings()) == []


def test_results_sort_by_fire_then_due(store):
    add_doc(
        store,
        "a",
        "health_policy",
        {"end_date": "2027-03-14", "premium_due_date": "2027-03-10"},
        ["x"],
    )
    found = reminders(store, date(2027, 3, 1), ReminderSettings())
    assert fires(found) == sorted(fires(found))


def test_people_are_the_owner_then_the_linked(store):
    add_doc(store, "d1", "health_policy", {"end_date": "2027-03-14"}, ["x"], owner="p2")
    assert reminders(store, date(2027, 3, 1), ReminderSettings())[0].person_ids[0] == "p2"


def test_every_rule_can_fire(store):
    docs = {
        "policy_renewal": ("life_policy", {"end_date": "2027-03-14"}),
        "premium_due": ("home_policy", {"premium_due_date": "2027-03-14"}),
        "warranty_end": (
            "warranty_card",
            {"purchase_date": "2026-03-15", "warranty_parts": [{"part": "All", "years": 1}]},
        ),
        "period_end": ("amc", {"period_end": "2027-03-14"}),
        "passport_expiry": ("passport", {"expiry_date": "2027-12-14"}),
        "licence_rc_puc": ("puc_certificate", {"expiry_date": "2027-03-14"}),
        "rent_end": ("rent_agreement", {"expiry_date": "2027-03-14"}),
        "card_expiry": ("card_front", {"expiry": "03/27"}),
        "card_payment_due": ("card_statement", {"payment_due_date": "2027-03-14"}),
        "next_checkup": ("prescription", {"next_visit": "2027-03-14"}),
    }
    assert {r.name for r in RULES} == set(docs)
    for name, (kind, fields) in docs.items():
        add_doc(store, name, kind, fields, ["x"])
    found = reminders(store, date(2027, 3, 10), ReminderSettings())
    assert {r.rule for r in found} == set(docs)
    assert DocType.puc_certificate
