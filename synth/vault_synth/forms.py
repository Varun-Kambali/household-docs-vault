"""One data-driven form layout per type that has no hand-drawn template.

A `FormSpec` lists the fields a page prints. Each `FormField.make` draws a value from the seeded
generator and returns the truth value with the text printed on the page. `draw_form` (in
`templates/form.py`) turns a spec into a page.
"""

import datetime as dt
import random
from collections.abc import Callable
from dataclasses import dataclass

from faker import Faker
from pydantic import JsonValue

from household_vault.checks import TEST_CARD_NUMBERS, luhn_valid, verhoeff_valid
from household_vault.doctypes import LIGHT_FIELDS, REQUIRED, DocType
from vault_synth import data
from vault_synth.household import CastMember
from vault_synth.templates.card_front import _network as network_of

Make = Callable[[random.Random, Faker, list[CastMember]], tuple[JsonValue, str]]

# Fields that print the household person (the first name on the page), or all of them.
PERSON_FIELDS = frozenset({"policyholder", "buyer", "holder", "patient", "person_name"})
PERSON_LIST_FIELDS = frozenset({"insured", "parties"})


@dataclass(frozen=True)
class FormField:
    name: str
    label: str
    make: Make


# Values that depend on each other, drawn together before the fields: a name to (truth, printed).
Joint = Callable[[random.Random], dict[str, tuple[JsonValue, str]]]

# The band at the top of a page names the document's own organisation. When the type prints
# one of these fields, the first of them in this order gives the band; otherwise (or when that
# field is left off the page) the band uses one of `FormSpec.issuers`.
ORG_PRIORITY = ("insurer", "bank", "employer", "hospital", "issuer", "brand", "seller", "provider")


@dataclass(frozen=True)
class FormSpec:
    title: str
    issuers: tuple[str, ...]
    fields: tuple[FormField, ...]
    person_label: str
    image_box: bool = False
    # filled from REQUIRED so the layout knows which rows may never roll "absent"
    required: frozenset[str] = frozenset()
    joint: Joint | None = None


def safe_digits(rng: random.Random, n: int) -> str:
    """n digits that can never pass as a real number: 12 digits fail Verhoeff (the Aadhaar
    check), 13 to 19 fail Luhn (the card check). Redrawn until they do."""
    while True:
        s = data.digits(rng, n)
        if n == 12 and verhoeff_valid(s):
            continue
        if 13 <= n <= 19 and luhn_valid(s):
            continue
        return s


def _label(name: str) -> str:
    return name.replace("_", " ").capitalize()


# ---- makers -------------------------------------------------------------------------------


def pick(*choices: str) -> Make:
    def make(rng: random.Random, fake: Faker, cast: list[CastMember]) -> tuple[JsonValue, str]:
        v = rng.choice(choices)
        return v, v

    return make


def person(rng: random.Random, fake: Faker, cast: list[CastMember]) -> tuple[JsonValue, str]:
    return cast[0].printed, cast[0].printed


def people(rng: random.Random, fake: Faker, cast: list[CastMember]) -> tuple[JsonValue, str]:
    names: list[JsonValue] = [c.printed for c in cast]
    return names, "\n".join(c.printed for c in cast)


def doctor(rng: random.Random, fake: Faker, cast: list[CastMember]) -> tuple[JsonValue, str]:
    v = f"Dr. {fake.name()}"
    return v, v


def nominee(rng: random.Random, fake: Faker, cast: list[CastMember]) -> tuple[JsonValue, str]:
    v = str(fake.name())
    return v, v


def past(lo: int, hi: int) -> Make:
    def make(rng: random.Random, fake: Faker, cast: list[CastMember]) -> tuple[JsonValue, str]:
        d = data.past_date(rng, lo, hi)
        return data.iso(d), data.dmy(d)

    return make


def future(lo: int, hi: int) -> Make:
    def make(rng: random.Random, fake: Faker, cast: list[CastMember]) -> tuple[JsonValue, str]:
        d = data.REFERENCE_DATE + dt.timedelta(days=rng.randint(lo, hi))
        return data.iso(d), data.dmy(d)

    return make


def money(*choices: int) -> Make:
    def make(rng: random.Random, fake: Faker, cast: list[CastMember]) -> tuple[JsonValue, str]:
        v = rng.choice(choices)
        return str(v), f"Rs. {data.indian_grouping(v)}"

    return make


def count(lo: int, hi: int) -> Make:
    def make(rng: random.Random, fake: Faker, cast: list[CastMember]) -> tuple[JsonValue, str]:
        v = str(rng.randint(lo, hi))
        return v, v

    return make


def ident(prefix: str, n: int = 8) -> Make:
    """A prefix and n safe digits, so no identifier is a bare Aadhaar or card shaped number."""

    def make(rng: random.Random, fake: Faker, cast: list[CastMember]) -> tuple[JsonValue, str]:
        v = f"{prefix}-{safe_digits(rng, n)}"
        return v, v

    return make


def alnum(prefix: str) -> Make:
    def make(rng: random.Random, fake: Faker, cast: list[CastMember]) -> tuple[JsonValue, str]:
        v = f"{prefix}{data.letters(rng, 2)}{data.digits(rng, 6)}"
        return v, v

    return make


def reserved_number(
    rng: random.Random, fake: Faker, cast: list[CastMember]
) -> tuple[JsonValue, str]:
    """The ZZ pattern only this project uses; no issuing authority starts a number with it."""
    v = f"ZZ{data.letters(rng, 1)}{data.digits(rng, 7)}"
    return v, v


def digits_id(n: int) -> Make:
    def make(rng: random.Random, fake: Faker, cast: list[CastMember]) -> tuple[JsonValue, str]:
        v = safe_digits(rng, n)
        return v, v

    return make


def helpline(rng: random.Random, fake: Faker, cast: list[CastMember]) -> tuple[JsonValue, str]:
    v = data.helpline(rng)
    return v, v


def address(rng: random.Random, fake: Faker, cast: list[CastMember]) -> tuple[JsonValue, str]:
    lines, _ = data.address_lines(rng)
    v = f"{lines[0]}, {lines[2]}"
    return v, v


def city(rng: random.Random, fake: Faker, cast: list[CastMember]) -> tuple[JsonValue, str]:
    v = rng.choice(data.CITIES)[0]
    return v, v


def last4(rng: random.Random, fake: Faker, cast: list[CastMember]) -> tuple[JsonValue, str]:
    """The last four digits of one of the networks' published test numbers, masked."""
    tail = rng.choice(sorted(TEST_CARD_NUMBERS))[-4:]
    return tail, f"XXXX XXXX XXXX {tail}"


def odometer(rng: random.Random, fake: Faker, cast: list[CastMember]) -> tuple[JsonValue, str]:
    v = rng.randint(4000, 120000)
    return str(v), data.indian_grouping(v)


def listing(items: tuple[str, ...], lo: int = 1, hi: int = 3) -> Make:
    def make(rng: random.Random, fake: Faker, cast: list[CastMember]) -> tuple[JsonValue, str]:
        picks = rng.sample(items, rng.randint(lo, min(hi, len(items))))
        values: list[JsonValue] = [*picks]
        return values, "\n".join(picks)

    return make


MEDICINES = (
    ("Metformin", "500 mg"),
    ("Amlodipine", "5 mg"),
    ("Pantoprazole", "40 mg"),
    ("Paracetamol", "650 mg"),
    ("Atorvastatin", "10 mg"),
)
TIMINGS = ("1-0-1", "0-0-1", "1-0-0")
DURATIONS = ("5 days", "10 days", "1 month")


def medicines(rng: random.Random, fake: Faker, cast: list[CastMember]) -> tuple[JsonValue, str]:
    vals: list[JsonValue] = []
    lines: list[str] = []
    for n, (name, dose) in enumerate(rng.sample(MEDICINES, rng.randint(2, 3))):
        timing, dur = rng.choice(TIMINGS), rng.choice(DURATIONS)
        vals.append({"name": name, "dose": dose, "timing": timing, "duration": dur})
        lines.append(f"{n + 1}. Tab {name} {dose}  {timing}  {dur}")
    return vals, "\n".join(lines)


def _f(name: str, make: Make, label: str | None = None) -> FormField:
    return FormField(name, label or _label(name), make)


INSURERS = (
    "Nilgiri General Insurance Company Limited",
    "Western Ghats Life Assurance Limited",
    "Tungabhadra Insurance Company Limited",
)
DEALERS = ("Sapphire Electronics", "Metro Home Appliances", "Lakeview Digital Store")
BRANDS = ("Aurora", "Vistara Home", "Kestrel", "Nimbus")
PRODUCTS = ("Split air conditioner", "Front-load washing machine", "Refrigerator", "Television")
HOSPITALS = tuple(data.HOSPITALS)
DEPARTMENTS = ("Radiology", "Cardiology", "Orthopaedics", "General Medicine")
DIAGNOSES = ("Type 2 diabetes mellitus", "Hypertension", "Acute gastritis", "Viral fever")
PROCEDURES = ("Endoscopy", "Cast application", "Minor wound repair")
ALLERGIES = ("Penicillin", "Sulfa drugs", "Dust")
EMPLOYERS = ("Northstar Software Private Limited", "Kaveri Systems Limited", "Orchard Labs")
DESIGNATIONS = ("Software Engineer", "Senior Analyst", "Project Lead", "Associate Manager")
INSTITUTES = ("Cauvery Institute of Technology", "Western Ghats University", "Hill Park College")


def _insurance(title: str, names: tuple[str, ...]) -> FormSpec:
    fields = {
        "insurer": _f("insurer", pick(*INSURERS)),
        "product": _f("product", pick("Secure Plan", "Protect Plus", "Shield Cover")),
        "policy_number": _f("policy_number", alnum("PL/"), "Policy number"),
        "policyholder": _f("policyholder", person, "Policyholder"),
        "insured": _f("insured", people, "Insured persons"),
        "nominee": _f("nominee", nominee),
        "sum_insured": _f("sum_insured", money(500000, 1000000, 2500000), "Sum insured"),
        "premium": _f("premium", money(8200, 14160, 21240, 33000)),
        "premium_frequency": _f("premium_frequency", pick("Annual", "Monthly", "Quarterly")),
        "start_date": _f("start_date", past(30, 330)),
        "end_date": _f("end_date", future(30, 330)),
        "premium_due_date": _f("premium_due_date", future(20, 300), "Next premium due"),
        "agent": _f("agent", pick("Direct", "Anand Insurance Services", "Lotus Advisors")),
        "claim_helpline": _f("claim_helpline", helpline, "Claims helpline"),
    }
    return FormSpec(title, INSURERS, tuple(fields[n] for n in names), "Policyholder")


def _form(
    title: str,
    issuers: tuple[str, ...],
    person_label: str,
    fields: tuple[FormField, ...],
    *,
    image_box: bool = False,
) -> FormSpec:
    return FormSpec(title, issuers, fields, person_label, image_box)


_PURCHASE_FIELDS = {
    "brand": _f("brand", pick(*BRANDS)),
    "product": _f("product", pick(*PRODUCTS)),
    "model": _f("model", alnum("MD")),
    "serial_number": _f("serial_number", alnum("SN"), "Serial number"),
    "seller": _f("seller", pick(*DEALERS)),
    "seller_location": _f("seller_location", city, "Seller location"),
    "buyer": _f("buyer", person, "Buyer"),
    "purchase_date": _f("purchase_date", past(60, 700), "Purchase date"),
    "amount": _f("amount", money(18500, 32000, 45990, 62000)),
    "period_start": _f("period_start", past(30, 330), "Cover starts"),
    "period_end": _f("period_end", future(30, 700), "Cover ends"),
    "visits": _f("visits", count(1, 4), "Visits a year"),
    "service_helpline": _f("service_helpline", helpline, "Service helpline"),
}


def _purchase(title: str, names: tuple[str, ...]) -> FormSpec:
    return _form(
        title,
        ("Service desk", "Customer care"),
        "Buyer",
        tuple(_PURCHASE_FIELDS[n] for n in names),
    )


def _identity(title: str, issuer: str, fields: tuple[FormField, ...]) -> FormSpec:
    return _form(title, (issuer,), "Holder", fields)


_HOLDER = _f("holder", person, "Name")
_NUMBER = _f("number", reserved_number, "Number")
_DOB = _f("date_of_birth", past(8000, 25000), "Date of birth")
_ISSUED = _f("issue_date", past(60, 3000), "Date of issue")
_EXPIRY = _f("expiry_date", future(200, 3000), "Valid until")
_ADDRESS = _f("address", address)


def _medical(title: str, names: tuple[str, ...], *, image_box: bool = False) -> FormSpec:
    fields = {
        "patient": _f("patient", person, "Patient"),
        "date": _f("date", past(3, 200)),
        "hospital": _f("hospital", pick(*HOSPITALS)),
        "doctor": _f("doctor", doctor),
        "department": _f("department", pick(*DEPARTMENTS)),
        "diagnoses": _f("diagnoses", listing(DIAGNOSES)),
        "procedures": _f("procedures", listing(PROCEDURES, 1, 2)),
        "allergies": _f("allergies", listing(ALLERGIES, 1, 2)),
        "medicines": _f("medicines", medicines, "Medicines on discharge"),
        "next_visit": _f("next_visit", future(10, 60), "Next visit"),
        "amount": _f("amount", money(12400, 48600, 96500, 143200), "Total amount"),
    }
    return _form(
        title, tuple(HOSPITALS[:3]), "Patient", tuple(fields[n] for n in names), image_box=image_box
    )


def _card(title: str, names: tuple[str, ...]) -> FormSpec:
    fields = {
        "bank": _f("bank", pick(*data.BANKS)),
        "card_name": _f("card_name", pick("Everyday Rewards", "Travel Plus", "Cashback Select")),
        "network": _f("network", pick("Visa", "Mastercard", "American Express")),
        "holder": _f("holder", person, "Card holder"),
        "last4": _f("last4", last4, "Card number"),
        "statement_date": _f("statement_date", past(3, 30), "Statement date"),
        "payment_due_date": _f("payment_due_date", future(5, 25), "Payment due date"),
        "total_due": _f("total_due", money(3420, 18800, 52400), "Total amount due"),
        "credit_limit": _f("credit_limit", money(100000, 250000, 500000), "Credit limit"),
        "annual_fee": _f("annual_fee", money(499, 999, 2500), "Annual fee"),
    }
    return _form(title, tuple(data.BANKS[:2]), "Card holder", tuple(fields[n] for n in names))


_LIGHT_TITLES = {
    DocType.sale_deed: "Sale Deed",
    DocType.rent_agreement: "Rental Agreement",
    DocType.khata: "Khata Certificate",
    DocType.property_tax_receipt: "Property Tax Receipt",
    DocType.encumbrance_certificate: "Encumbrance Certificate",
    DocType.utility_bill: "Electricity Bill",
    DocType.registration_certificate: "Certificate of Registration",
    DocType.puc_certificate: "Pollution Under Control Certificate",
    DocType.fastag: "FASTag Issuance Details",
    DocType.vehicle_service_record: "Vehicle Service Invoice",
    DocType.payslip: "Payslip",
    DocType.offer_letter: "Offer Letter",
    DocType.appointment_letter: "Letter of Appointment",
    DocType.appraisal_letter: "Annual Appraisal Letter",
    DocType.relieving_letter: "Relieving Letter",
    DocType.experience_letter: "Experience Certificate",
    DocType.certificate: "Certificate of Completion",
    DocType.marksheet: "Statement of Marks",
    DocType.degree: "Degree Certificate",
    DocType.form_16: "Form No. 16",
    DocType.itr_acknowledgement: "Income Tax Return Acknowledgement",
    DocType.tax_proof: "Investment Proof",
}
# expiry_date is printed only on these, under the label the page would use
_LIGHT_EXPIRY = {
    DocType.rent_agreement: ("End of term", future(60, 700)),
    DocType.utility_bill: ("Due date", future(5, 25)),
    DocType.registration_certificate: ("Valid till", future(200, 3000)),
    DocType.puc_certificate: ("Valid till", future(30, 330)),
}
# days after the document date, for the expiry that goes with it
_LIGHT_EXPIRY_DAYS: dict[DocType, Callable[[random.Random], int]] = {
    DocType.rent_agreement: lambda rng: 365 * rng.randint(1, 3) - 1,
    DocType.utility_bill: lambda rng: rng.randint(10, 20),
    DocType.registration_certificate: lambda rng: 5475,
    DocType.puc_certificate: lambda rng: 365,
}
_LIGHT_ISSUERS = {
    "sale_deed": "Office of the Sub-Registrar",
    "rent_agreement": "Rental Agreement",
    "khata": "Municipal Corporation",
    "property_tax_receipt": "Municipal Corporation",
    "encumbrance_certificate": "Office of the Sub-Registrar",
    "utility_bill": "Malnad Power Supply Company",
    "registration_certificate": "Regional Transport Office",
    "puc_certificate": "Authorised Testing Centre",
    "fastag": "Nilgiri Bank",
    "vehicle_service_record": "Greenfield Motors Service Centre",
    "form_16": "Employer",
    "itr_acknowledgement": "Income Tax Department",
    "tax_proof": "Investment Declaration",
}
_PREFIXES = {
    "registration_number": "KA",
    "khata_number": "KH",
    "receipt_number": "RC",
    "certificate_number": "CN",
    "consumer_number": "CS",
    "tag_id": "TG",
    "acknowledgement_number": "AK",
    "roll_number": "RN",
    "credential_id": "CR",
}
_LIGHT_TEXT: dict[str, Make] = {
    "provider": pick("Malnad Power Supply Company", "Cauvery Electricity Board"),
    "employer": pick(*EMPLOYERS),
    "designation": pick(*DESIGNATIONS),
    "issuer": pick(*INSTITUTES),
    "section": pick("80C", "80D", "24(b)"),
}


def _light_make(name: str, kind: str) -> Make:
    if name in _LIGHT_TEXT:
        return _LIGHT_TEXT[name]
    if name == "assessment_year":
        return pick("2025-26", "2026-27")
    if name == "odometer_km":
        return odometer
    if kind == "amount":
        return money(1500, 12500, 38000, 120000)
    return ident(_PREFIXES.get(name, "ID"), 15 if name == "acknowledgement_number" else 8)


def _light(doc_type: DocType) -> FormSpec:
    fields = [
        _f("person_name", person, "Name"),
        _f("document_date", past(5, 400), "Date"),
    ]
    fields += [
        _f(name, _light_make(name, kind), "Odometer (km)" if name == "odometer_km" else None)
        for name, kind in LIGHT_FIELDS[doc_type]
    ]
    if doc_type in _LIGHT_EXPIRY:
        label, make = _LIGHT_EXPIRY[doc_type]
        fields.append(_f("expiry_date", make, label))
    issuer = _LIGHT_ISSUERS.get(doc_type.value, "Issuing authority")
    return _form(_LIGHT_TITLES[doc_type], (issuer,), "Name", tuple(fields))


_D = DocType
_SPECS: dict[DocType, FormSpec] = {
    _D.life_policy: _insurance(
        "Life Insurance Policy Schedule",
        (
            "insurer",
            "product",
            "policy_number",
            "policyholder",
            "insured",
            "nominee",
            "sum_insured",
            "premium",
            "premium_frequency",
            "start_date",
            "end_date",
            "premium_due_date",
            "agent",
            "claim_helpline",
        ),
    ),
    _D.home_policy: _insurance(
        "Home Insurance Policy Schedule",
        (
            "insurer",
            "product",
            "policy_number",
            "policyholder",
            "sum_insured",
            "premium",
            "start_date",
            "end_date",
            "claim_helpline",
        ),
    ),
    _D.travel_policy: _insurance(
        "Travel Insurance Certificate",
        (
            "insurer",
            "policy_number",
            "policyholder",
            "insured",
            "sum_insured",
            "premium",
            "start_date",
            "end_date",
            "claim_helpline",
        ),
    ),
    _D.gadget_policy: _insurance(
        "Mobile and Gadget Protection Plan",
        (
            "insurer",
            "product",
            "policy_number",
            "policyholder",
            "sum_insured",
            "premium",
            "start_date",
            "end_date",
            "claim_helpline",
        ),
    ),
    _D.accident_policy: _insurance(
        "Personal Accident Insurance Schedule",
        (
            "insurer",
            "policy_number",
            "policyholder",
            "insured",
            "nominee",
            "sum_insured",
            "premium",
            "start_date",
            "end_date",
            "claim_helpline",
        ),
    ),
    _D.extended_warranty: _purchase(
        "Extended Warranty Certificate",
        (
            "brand",
            "product",
            "model",
            "serial_number",
            "seller",
            "seller_location",
            "buyer",
            "purchase_date",
            "amount",
            "period_start",
            "period_end",
            "service_helpline",
        ),
    ),
    _D.amc: _purchase(
        "Annual Maintenance Contract",
        (
            "brand",
            "product",
            "serial_number",
            "seller",
            "buyer",
            "purchase_date",
            "amount",
            "period_start",
            "period_end",
            "visits",
            "service_helpline",
        ),
    ),
    _D.appliance_service_record: _purchase(
        "Service Report",
        (
            "brand",
            "product",
            "serial_number",
            "seller",
            "buyer",
            "purchase_date",
            "amount",
            "service_helpline",
        ),
    ),
    _D.passport: _identity(
        "Passport (Specimen)",
        "Republic of India",
        (_HOLDER, _NUMBER, _DOB, _ISSUED, _EXPIRY),
    ),
    _D.voter_id: _identity(
        "Elector Photo Identity Card",
        "Election Commission",
        (_HOLDER, _NUMBER, _DOB, _ADDRESS),
    ),
    _D.driving_licence: _identity(
        "Driving Licence",
        "Transport Department",
        (_HOLDER, _NUMBER, _DOB, _ISSUED, _EXPIRY, _ADDRESS),
    ),
    _D.birth_certificate: _identity(
        "Certificate of Birth",
        "Registrar of Births and Deaths",
        (_HOLDER, _NUMBER, _DOB, _ISSUED),
    ),
    _D.marriage_certificate: _identity(
        "Certificate of Registration of Marriage",
        "Office of the Registrar of Marriages",
        (_f("parties", people, "Parties"), _NUMBER, _ISSUED),
    ),
    _D.card_statement: _card(
        "Credit Card Statement",
        (
            "bank",
            "card_name",
            "holder",
            "last4",
            "statement_date",
            "payment_due_date",
            "total_due",
            "credit_limit",
        ),
    ),
    _D.card_welcome_letter: _card(
        "Welcome to your new card",
        ("bank", "card_name", "network", "holder", "last4", "credit_limit", "annual_fee"),
    ),
    _D.scan_photo: _medical(
        "Ultrasound Images", ("patient", "date", "hospital", "department"), image_box=True
    ),
    _D.scan_report: _medical(
        "Radiology Report", ("patient", "date", "hospital", "doctor", "department", "diagnoses")
    ),
    _D.discharge_summary: _medical(
        "Discharge Summary",
        (
            "patient",
            "date",
            "hospital",
            "doctor",
            "department",
            "diagnoses",
            "procedures",
            "allergies",
            "medicines",
            "next_visit",
        ),
    ),
    _D.hospital_bill: _medical("Final Bill", ("patient", "date", "hospital", "amount")),
    **{t: _light(t) for t in _LIGHT_TITLES},
}


def _entry(d: dt.date) -> tuple[JsonValue, str]:
    return data.iso(d), data.dmy(d)


def _joint(
    doc_type: DocType, names: frozenset[str], rng: random.Random
) -> dict[str, tuple[JsonValue, str]]:
    """Dates in the order a real page keeps them, and a card's network with its own last four."""
    ref = data.REFERENCE_DATE
    out: dict[str, tuple[JsonValue, str]] = {}

    def day(n: int) -> dt.timedelta:
        return dt.timedelta(days=n)

    if "start_date" in names:
        start = data.past_date(rng, 30, 330)
        end = data.plus_year(start)
        lo = max(start + day(1), ref)
        out["start_date"], out["end_date"] = _entry(start), _entry(end)
        if "premium_due_date" in names:
            out["premium_due_date"] = _entry(lo + day(rng.randint(0, (end - lo).days)))
    if "purchase_date" in names:
        bought = data.past_date(rng, 30, 700)
        out["purchase_date"] = _entry(bought)
        if "period_start" in names:
            begin = bought + day(rng.randint(0, 30))
            out["period_start"] = _entry(begin)
            out["period_end"] = _entry(data.plus_year(begin, rng.randint(1, 3)))
    if "document_date" in names:
        doc = data.past_date(rng, 5, 400)
        out["document_date"] = _entry(doc)
        if "expiry_date" in names:
            out["expiry_date"] = _entry(doc + day(_LIGHT_EXPIRY_DAYS[doc_type](rng)))
    elif "issue_date" in names or "date_of_birth" in names:
        born = data.past_date(rng, 8000, 25000)
        if "date_of_birth" in names:
            out["date_of_birth"] = _entry(born)
        if "issue_date" in names:
            # a birth certificate is issued soon after the birth; the others later in life
            birth = "date_of_birth" in names and "expiry_date" not in names
            issued = born + day(rng.randint(5, 60)) if birth else data.past_date(rng, 60, 3000)
            out["issue_date"] = _entry(issued)
            if "expiry_date" in names:
                out["expiry_date"] = _entry(issued + day(3650))
    if "statement_date" in names:
        stated = data.past_date(rng, 3, 30)
        out["statement_date"] = _entry(stated)
        out["payment_due_date"] = _entry(stated + day(rng.randint(15, 25)))
    if "last4" in names:
        number = rng.choice(sorted(TEST_CARD_NUMBERS))
        out["last4"] = (number[-4:], f"XXXX XXXX XXXX {number[-4:]}")
        if "network" in names:
            out["network"] = (network_of(number), network_of(number))
    if "next_visit" in names and "date" in names:
        seen = data.past_date(rng, 3, 200)
        out["date"] = _entry(seen)
        out["next_visit"] = _entry(max(seen, ref) + day(rng.randint(10, 60)))
    elif "date" in names:
        out["date"] = _entry(data.past_date(rng, 3, 200))
    return out


def _with_joint(doc_type: DocType, spec: FormSpec) -> FormSpec:
    names = frozenset(f.name for f in spec.fields)

    def joint(rng: random.Random) -> dict[str, tuple[JsonValue, str]]:
        return _joint(doc_type, names, rng)

    return FormSpec(
        spec.title,
        spec.issuers,
        spec.fields,
        spec.person_label,
        spec.image_box,
        frozenset(REQUIRED[doc_type]),
        joint,
    )


FORM_SPECS: dict[DocType, FormSpec] = {t: _with_joint(t, s) for t, s in _SPECS.items()}
