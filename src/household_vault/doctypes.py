"""Every document type the app reads in v1 (design 5.3). Values are stored in the database."""

from dataclasses import dataclass
from enum import StrEnum

from household_vault.fieldkinds import FieldKind


class DocType(StrEnum):
    # Insurance
    life_policy = "life_policy"
    health_policy = "health_policy"
    vehicle_policy = "vehicle_policy"
    home_policy = "home_policy"
    travel_policy = "travel_policy"
    gadget_policy = "gadget_policy"
    accident_policy = "accident_policy"
    # Purchases
    tax_invoice = "tax_invoice"
    warranty_card = "warranty_card"
    extended_warranty = "extended_warranty"
    amc = "amc"
    appliance_service_record = "appliance_service_record"
    # Identity
    aadhaar = "aadhaar"
    pan = "pan"
    passport = "passport"
    voter_id = "voter_id"
    driving_licence = "driving_licence"
    birth_certificate = "birth_certificate"
    marriage_certificate = "marriage_certificate"
    # Home
    sale_deed = "sale_deed"
    rent_agreement = "rent_agreement"
    khata = "khata"
    property_tax_receipt = "property_tax_receipt"
    encumbrance_certificate = "encumbrance_certificate"
    utility_bill = "utility_bill"
    # Vehicle
    registration_certificate = "registration_certificate"
    puc_certificate = "puc_certificate"
    fastag = "fastag"
    vehicle_service_record = "vehicle_service_record"
    # Work and education
    payslip = "payslip"
    offer_letter = "offer_letter"
    appointment_letter = "appointment_letter"
    appraisal_letter = "appraisal_letter"
    relieving_letter = "relieving_letter"
    experience_letter = "experience_letter"
    certificate = "certificate"
    marksheet = "marksheet"
    degree = "degree"
    # Tax
    form_16 = "form_16"
    itr_acknowledgement = "itr_acknowledgement"
    tax_proof = "tax_proof"
    # Cards
    card_front = "card_front"
    card_statement = "card_statement"
    card_welcome_letter = "card_welcome_letter"
    # Medical
    prescription = "prescription"
    lab_report = "lab_report"
    scan_photo = "scan_photo"
    scan_report = "scan_report"
    discharge_summary = "discharge_summary"
    hospital_bill = "hospital_bill"
    visit_recording = "visit_recording"
    # Anything the router cannot place
    other = "other"


class Area(StrEnum):
    """A folder group in the vault. The values are stored in the database."""

    insurance = "insurance"
    purchases = "purchases"
    identity = "identity"
    vehicle = "vehicle"
    work = "work"
    education = "education"
    tax = "tax"
    cards = "cards"
    medical = "medical"
    property = "property"
    rent = "rent"
    utilities = "utilities"


AREA_FOLDER: dict[Area, str] = {a: a.value.title() for a in Area}

_D = DocType
_AREA_TYPES: dict[Area, tuple[DocType, ...]] = {
    Area.insurance: (
        _D.life_policy,
        _D.health_policy,
        _D.vehicle_policy,
        _D.home_policy,
        _D.travel_policy,
        _D.gadget_policy,
        _D.accident_policy,
    ),
    Area.purchases: (
        _D.tax_invoice,
        _D.warranty_card,
        _D.extended_warranty,
        _D.amc,
        _D.appliance_service_record,
    ),
    Area.identity: (
        _D.aadhaar,
        _D.pan,
        _D.passport,
        _D.voter_id,
        _D.driving_licence,
        _D.birth_certificate,
        _D.marriage_certificate,
    ),
    Area.vehicle: (
        _D.registration_certificate,
        _D.puc_certificate,
        _D.fastag,
        _D.vehicle_service_record,
    ),
    Area.work: (
        _D.payslip,
        _D.offer_letter,
        _D.appointment_letter,
        _D.appraisal_letter,
        _D.relieving_letter,
        _D.experience_letter,
    ),
    Area.education: (_D.certificate, _D.marksheet, _D.degree),
    Area.tax: (_D.form_16, _D.itr_acknowledgement, _D.tax_proof),
    Area.cards: (_D.card_front, _D.card_statement, _D.card_welcome_letter),
    Area.medical: (
        _D.prescription,
        _D.lab_report,
        _D.scan_photo,
        _D.scan_report,
        _D.discharge_summary,
        _D.hospital_bill,
        _D.visit_recording,
    ),
    Area.property: (_D.sale_deed, _D.khata, _D.property_tax_receipt, _D.encumbrance_certificate),
    Area.rent: (_D.rent_agreement,),
    Area.utilities: (_D.utility_bill,),
}
AREA: dict[DocType, Area] = {t: a for a, types in _AREA_TYPES.items() for t in types}

SUBFOLDER: dict[DocType, str] = {
    _D.prescription: "Reports",
    _D.lab_report: "Reports",
    _D.scan_photo: "Scans",
    _D.scan_report: "Scans",
    _D.discharge_summary: "Hospital stays",
    _D.hospital_bill: "Hospital stays",
    _D.visit_recording: "Recordings",
}

_CORE_AREAS = {Area.insurance, Area.purchases, Area.identity, Area.cards, Area.medical}
CORE: frozenset[DocType] = frozenset(t for t, a in AREA.items() if a in _CORE_AREAS)
LIGHT: frozenset[DocType] = frozenset(t for t, a in AREA.items() if a not in _CORE_AREAS)


@dataclass(frozen=True)
class OwnerRule:
    """Who a document belongs to. `home` documents belong to the household and are linked to
    the people named by `linked_fields`; otherwise the person named by `owner_fields` owns it.
    A field that holds a list gives its first name that matches the household."""

    home: bool
    owner_fields: tuple[str, ...]
    linked_fields: tuple[str, ...]


def _rule(types: tuple[DocType, ...], rule: OwnerRule) -> dict[DocType, OwnerRule]:
    return dict.fromkeys(types, rule)


# Every group is listed by name, so a new type without a rule is missing here and the golden
# test fails, instead of quietly getting a default.
OWNER: dict[DocType, OwnerRule] = {
    **_rule(
        (_D.life_policy, _D.health_policy, _D.travel_policy, _D.gadget_policy, _D.accident_policy),
        OwnerRule(False, ("policyholder",), ("policyholder", "insured")),
    ),
    **_rule((_D.vehicle_policy,), OwnerRule(False, ("policyholder",), ("policyholder",))),
    **_rule((_D.home_policy,), OwnerRule(True, (), ("policyholder", "insured"))),
    **_rule(_AREA_TYPES[Area.purchases], OwnerRule(True, (), ("buyer",))),
    **_rule(
        (
            _D.aadhaar,
            _D.pan,
            _D.passport,
            _D.voter_id,
            _D.driving_licence,
            _D.birth_certificate,
        ),
        OwnerRule(False, ("holder",), ("holder",)),
    ),
    **_rule((_D.marriage_certificate,), OwnerRule(False, ("parties",), ("parties",))),
    **_rule(_AREA_TYPES[Area.cards], OwnerRule(False, ("holder",), ("holder",))),
    **_rule(
        (
            _D.prescription,
            _D.lab_report,
            _D.scan_photo,
            _D.scan_report,
            _D.discharge_summary,
            _D.hospital_bill,
        ),
        OwnerRule(False, ("patient",), ("patient",)),
    ),
    **_rule((_D.visit_recording,), OwnerRule(False, ("patient",), ())),
    **_rule(
        (*_AREA_TYPES[Area.property], *_AREA_TYPES[Area.rent], *_AREA_TYPES[Area.utilities]),
        OwnerRule(True, (), ("person_name",)),
    ),
    **_rule(
        (
            *_AREA_TYPES[Area.vehicle],
            *_AREA_TYPES[Area.work],
            *_AREA_TYPES[Area.education],
            *_AREA_TYPES[Area.tax],
        ),
        OwnerRule(False, ("person_name",), ("person_name",)),
    ),
}

# What each light type prints besides person_name, document_date and expiry_date.
LIGHT_FIELDS: dict[DocType, tuple[tuple[str, FieldKind], ...]] = {
    _D.sale_deed: (("registration_number", "identifier"),),
    _D.rent_agreement: (("rent_amount", "amount"), ("deposit", "amount")),
    _D.khata: (("khata_number", "identifier"),),
    _D.property_tax_receipt: (("receipt_number", "identifier"), ("amount", "amount")),
    _D.encumbrance_certificate: (("certificate_number", "identifier"),),
    _D.utility_bill: (("provider", "text"), ("consumer_number", "identifier")),
    _D.registration_certificate: (("registration_number", "identifier"),),
    _D.puc_certificate: (
        ("registration_number", "identifier"),
        ("certificate_number", "identifier"),
    ),
    _D.fastag: (("registration_number", "identifier"), ("tag_id", "identifier")),
    _D.vehicle_service_record: (
        ("registration_number", "identifier"),
        ("odometer_km", "amount"),
    ),
    _D.payslip: (("employer", "text"), ("net_pay", "amount")),
    _D.offer_letter: (("employer", "text"), ("designation", "text")),
    _D.appointment_letter: (("employer", "text"), ("designation", "text")),
    _D.appraisal_letter: (("employer", "text"), ("designation", "text")),
    _D.relieving_letter: (("employer", "text"), ("designation", "text")),
    _D.experience_letter: (("employer", "text"), ("designation", "text")),
    _D.certificate: (("issuer", "text"), ("credential_id", "identifier")),
    _D.marksheet: (("issuer", "text"), ("roll_number", "identifier")),
    _D.degree: (("issuer", "text"), ("roll_number", "identifier")),
    _D.form_16: (("employer", "text"), ("assessment_year", "identifier")),
    _D.itr_acknowledgement: (
        ("acknowledgement_number", "identifier"),
        ("assessment_year", "identifier"),
    ),
    _D.tax_proof: (("section", "text"), ("amount", "amount")),
}

_POLICIES = (
    _D.life_policy,
    _D.health_policy,
    _D.home_policy,
    _D.travel_policy,
    _D.gadget_policy,
    _D.accident_policy,
)
_IDENTITY_PLAIN = (_D.aadhaar, _D.pan)
_IDENTITY_DATED = (_D.passport, _D.voter_id, _D.driving_licence, _D.birth_certificate)
_SCANS_AND_STAYS = (_D.scan_photo, _D.scan_report, _D.discharge_summary, _D.hospital_bill)
_LIGHT_TYPES = tuple(t for t in AREA if t in LIGHT)

DATE_FIELD: dict[DocType, str | None] = {
    **dict.fromkeys((*_POLICIES, _D.vehicle_policy), "start_date"),
    _D.tax_invoice: "invoice_date",
    **dict.fromkeys(
        (_D.warranty_card, _D.extended_warranty, _D.amc, _D.appliance_service_record),
        "purchase_date",
    ),
    **dict.fromkeys(_IDENTITY_PLAIN, None),
    **dict.fromkeys((*_IDENTITY_DATED, _D.marriage_certificate), "issue_date"),
    _D.card_front: None,
    _D.card_statement: "statement_date",
    _D.card_welcome_letter: None,
    **dict.fromkeys(
        (_D.prescription, _D.lab_report, *_SCANS_AND_STAYS),
        "date",
    ),
    _D.visit_recording: None,
    **dict.fromkeys(_LIGHT_TYPES, "document_date"),
}

_POLICY_REQUIRED = frozenset({"policy_number", "end_date"})
_PURCHASE_REQUIRED = frozenset({"product", "purchase_date"})
_MEDICAL_REQUIRED = frozenset({"patient", "date"})
REQUIRED: dict[DocType, frozenset[str]] = {
    **dict.fromkeys(_POLICIES, _POLICY_REQUIRED),
    _D.vehicle_policy: _POLICY_REQUIRED | {"registration_number"},
    _D.tax_invoice: frozenset({"seller", "invoice_date"}),
    _D.warranty_card: frozenset({"brand", "purchase_date"}),
    **dict.fromkeys(
        (_D.extended_warranty, _D.amc, _D.appliance_service_record), _PURCHASE_REQUIRED
    ),
    **dict.fromkeys((*_IDENTITY_PLAIN, *_IDENTITY_DATED), frozenset({"holder", "number"})),
    _D.marriage_certificate: frozenset({"number"}),
    _D.card_front: frozenset({"bank", "number"}),
    _D.card_statement: frozenset({"bank", "last4"}),
    _D.card_welcome_letter: frozenset({"bank", "last4"}),
    **dict.fromkeys((_D.prescription, _D.lab_report, *_SCANS_AND_STAYS), _MEDICAL_REQUIRED),
    _D.visit_recording: frozenset(),
    **dict.fromkeys(_LIGHT_TYPES, frozenset({"document_date"})),
}

_POLICY_KEY = ("policy_number", "start_date")
_MEDICAL_KEY = ("patient", "date")
COPY_KEY: dict[DocType, tuple[str, ...]] = {
    **dict.fromkeys((*_POLICIES, _D.vehicle_policy), _POLICY_KEY),
    _D.tax_invoice: ("invoice_number",),
    _D.warranty_card: ("serial_number",),
    **dict.fromkeys(
        (_D.extended_warranty, _D.amc, _D.appliance_service_record),
        ("serial_number", "purchase_date"),
    ),
    **dict.fromkeys((*_IDENTITY_PLAIN, *_IDENTITY_DATED, _D.marriage_certificate), ("number",)),
    _D.card_front: ("bank", "expiry", "last4"),
    _D.card_statement: ("last4", "statement_date"),
    _D.card_welcome_letter: ("bank", "last4"),
    _D.prescription: (*_MEDICAL_KEY, "doctor"),
    _D.lab_report: (*_MEDICAL_KEY, "lab"),
    **dict.fromkeys(_SCANS_AND_STAYS, (*_MEDICAL_KEY, "hospital")),
    _D.visit_recording: (),
    **{t: (LIGHT_FIELDS[t][0][0], "document_date") for t in _LIGHT_TYPES},
}

LABEL: dict[DocType, str] = {
    _D.life_policy: "Life policy",
    _D.health_policy: "Health policy",
    _D.vehicle_policy: "Vehicle policy",
    _D.home_policy: "Home policy",
    _D.travel_policy: "Travel policy",
    _D.gadget_policy: "Gadget policy",
    _D.accident_policy: "Accident policy",
    _D.tax_invoice: "Invoice",
    _D.warranty_card: "Warranty card",
    _D.extended_warranty: "Extended warranty",
    _D.amc: "Maintenance contract",
    _D.appliance_service_record: "Service record",
    _D.aadhaar: "Aadhaar",
    _D.pan: "PAN card",
    _D.passport: "Passport",
    _D.voter_id: "Voter ID",
    _D.driving_licence: "Driving licence",
    _D.birth_certificate: "Birth certificate",
    _D.marriage_certificate: "Marriage certificate",
    _D.sale_deed: "Sale deed",
    _D.rent_agreement: "Rent agreement",
    _D.khata: "Khata",
    _D.property_tax_receipt: "Property tax receipt",
    _D.encumbrance_certificate: "Encumbrance certificate",
    _D.utility_bill: "Utility bill",
    _D.registration_certificate: "RC",
    _D.puc_certificate: "PUC certificate",
    _D.fastag: "FASTag",
    _D.vehicle_service_record: "Vehicle service record",
    _D.payslip: "Payslip",
    _D.offer_letter: "Offer letter",
    _D.appointment_letter: "Appointment letter",
    _D.appraisal_letter: "Appraisal letter",
    _D.relieving_letter: "Relieving letter",
    _D.experience_letter: "Experience letter",
    _D.certificate: "Certificate",
    _D.marksheet: "Marksheet",
    _D.degree: "Degree",
    _D.form_16: "Form 16",
    _D.itr_acknowledgement: "ITR acknowledgement",
    _D.tax_proof: "Tax proof",
    _D.card_front: "Card",
    _D.card_statement: "Card statement",
    _D.card_welcome_letter: "Card welcome letter",
    _D.prescription: "Prescription",
    _D.lab_report: "Lab report",
    _D.scan_photo: "Scan",
    _D.scan_report: "Scan report",
    _D.discharge_summary: "Discharge summary",
    _D.hospital_bill: "Hospital bill",
    _D.visit_recording: "Visit recording",
}
