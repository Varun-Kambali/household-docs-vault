"""Every document type the app reads in v1 (design 5.3). Values are stored in the database."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # the schemas package imports this module, so only the type is imported here
    from household_vault.schemas._coerce import FieldKind


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


OWNER: dict[DocType, OwnerRule] = {}
for _t in AREA:
    if _t is _D.visit_recording:
        OWNER[_t] = OwnerRule(False, ("patient",), ())
    elif AREA[_t] is Area.insurance:
        if _t is _D.home_policy:
            OWNER[_t] = OwnerRule(True, (), ("policyholder", "insured"))
        elif _t is _D.vehicle_policy:
            OWNER[_t] = OwnerRule(False, ("policyholder",), ("policyholder",))
        else:
            OWNER[_t] = OwnerRule(False, ("policyholder",), ("policyholder", "insured"))
    elif AREA[_t] is Area.purchases:
        OWNER[_t] = OwnerRule(True, (), ("buyer",))
    elif AREA[_t] is Area.identity:
        field = ("parties",) if _t is _D.marriage_certificate else ("holder",)
        OWNER[_t] = OwnerRule(False, field, field)
    elif AREA[_t] is Area.cards:
        OWNER[_t] = OwnerRule(False, ("holder",), ("holder",))
    elif AREA[_t] is Area.medical:
        OWNER[_t] = OwnerRule(False, ("patient",), ("patient",))
    elif AREA[_t] in (Area.property, Area.rent, Area.utilities):
        OWNER[_t] = OwnerRule(True, (), ("person_name",))
    else:  # vehicle, work, education, tax
        OWNER[_t] = OwnerRule(False, ("person_name",), ("person_name",))

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

DATE_FIELD: dict[DocType, str | None] = {}
REQUIRED: dict[DocType, frozenset[str]] = {}
COPY_KEY: dict[DocType, tuple[str, ...]] = {}
for _t in AREA:
    _area = AREA[_t]
    if _area is Area.insurance:
        DATE_FIELD[_t] = "start_date"
        REQUIRED[_t] = frozenset({"policy_number", "end_date"})
        COPY_KEY[_t] = ("policy_number", "start_date")
        if _t is _D.vehicle_policy:
            REQUIRED[_t] |= {"registration_number"}
    elif _t is _D.tax_invoice:
        DATE_FIELD[_t] = "invoice_date"
        REQUIRED[_t] = frozenset({"seller", "invoice_date"})
        COPY_KEY[_t] = ("invoice_number",)
    elif _t is _D.warranty_card:
        DATE_FIELD[_t] = "purchase_date"
        REQUIRED[_t] = frozenset({"brand", "purchase_date"})
        COPY_KEY[_t] = ("serial_number",)
    elif _area is Area.purchases:
        DATE_FIELD[_t] = "purchase_date"
        REQUIRED[_t] = frozenset({"product", "purchase_date"})
        COPY_KEY[_t] = ("serial_number", "purchase_date")
    elif _area is Area.identity:
        DATE_FIELD[_t] = None if _t in (_D.aadhaar, _D.pan) else "issue_date"
        if _t is _D.marriage_certificate:
            REQUIRED[_t] = frozenset({"number"})
        else:
            REQUIRED[_t] = frozenset({"holder", "number"})
        COPY_KEY[_t] = ("number",)
    elif _t is _D.card_front:
        DATE_FIELD[_t] = None
        REQUIRED[_t] = frozenset({"bank", "number"})
        COPY_KEY[_t] = ("bank", "expiry", "last4")
    elif _t is _D.card_statement:
        DATE_FIELD[_t] = "statement_date"
        REQUIRED[_t] = frozenset({"bank", "last4"})
        COPY_KEY[_t] = ("last4", "statement_date")
    elif _area is Area.cards:
        DATE_FIELD[_t] = None
        REQUIRED[_t] = frozenset({"bank", "last4"})
        COPY_KEY[_t] = ("bank", "last4")
    elif _t is _D.visit_recording:
        DATE_FIELD[_t] = None
        REQUIRED[_t] = frozenset()
        COPY_KEY[_t] = ()
    elif _area is Area.medical:
        who = {_D.prescription: "doctor", _D.lab_report: "lab"}.get(_t, "hospital")
        DATE_FIELD[_t] = "date"
        REQUIRED[_t] = frozenset({"patient", "date"})
        COPY_KEY[_t] = ("patient", "date", who)
    else:
        DATE_FIELD[_t] = "document_date"
        REQUIRED[_t] = frozenset({"document_date"})
        COPY_KEY[_t] = (LIGHT_FIELDS[_t][0][0], "document_date")

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
