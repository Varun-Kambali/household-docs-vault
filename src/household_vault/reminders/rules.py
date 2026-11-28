"""The reminder rules (design 5.6) and their default lead times."""

from dataclasses import dataclass
from datetime import date, timedelta

from household_vault.doctypes import DocType as D
from household_vault.search.dates import add_months


@dataclass(frozen=True)
class Days:
    n: int


@dataclass(frozen=True)
class Months:
    n: int


Lead = Days | Months


@dataclass(frozen=True)
class Rule:
    name: str
    types: frozenset[D]
    date: str  # a DATE_ROLES role, "warranty_parts" or "card_expiry"
    leads: tuple[Lead, ...]
    calendar: bool
    verb: str


_POLICIES = frozenset(
    {
        D.life_policy,
        D.health_policy,
        D.vehicle_policy,
        D.home_policy,
        D.travel_policy,
        D.gadget_policy,
        D.accident_policy,
    }
)

RULES: tuple[Rule, ...] = (
    Rule("policy_renewal", _POLICIES, "renewal", (Days(60), Days(30), Days(7)), True, "Renew"),
    Rule("premium_due", _POLICIES, "due", (Days(60), Days(30), Days(7)), False, "Pay premium for"),
    Rule("warranty_end", frozenset({D.warranty_card}), "warranty_parts", (Days(30),), True,
         "Warranty ends for"),
    Rule("period_end", frozenset({D.extended_warranty, D.amc}), "expiry", (Days(30),), True,
         "Cover ends for"),
    Rule("passport_expiry", frozenset({D.passport}), "expiry", (Months(9),), True, "Renew"),
    Rule(
        "licence_rc_puc",
        frozenset({D.driving_licence, D.registration_certificate, D.puc_certificate}),
        "expiry",
        (Days(30), Days(15)),
        True,
        "Renew",
    ),
    Rule("rent_end", frozenset({D.rent_agreement}), "expiry", (Days(60),), True,
         "Rent agreement ends:"),
    Rule("card_expiry", frozenset({D.card_front}), "card_expiry", (Days(30),), True,
         "Card expires:"),
    Rule("card_payment_due", frozenset({D.card_statement}), "due", (Days(5), Days(1)), False,
         "Pay"),
    Rule(
        "next_checkup",
        frozenset({D.prescription, D.scan_photo, D.scan_report, D.discharge_summary,
                   D.hospital_bill}),
        "due",
        (Days(3), Days(1)),
        False,
        "Checkup due:",
    ),
)  # fmt: skip

RULES_BY_NAME: dict[str, Rule] = {r.name: r for r in RULES}


def lead_key(lead: Lead) -> str:
    return f"d{lead.n}" if isinstance(lead, Days) else f"m{lead.n}"


def fire_date(due: date, lead: Lead) -> date:
    """The day a reminder fires: days back, or months back clamped to the month's end."""
    if isinstance(lead, Days):
        return due - timedelta(days=lead.n)
    return add_months(due, -lead.n)
